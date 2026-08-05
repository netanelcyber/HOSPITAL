"""Batch scoring script for MIMIC-IV cohorts.

Scores all patients in a cohort using all 5 feature phases.
Outputs structured results for downstream analysis.
"""

from __future__ import annotations

import logging
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional
import json
from datetime import datetime

from features.lab_interpretation import LabInterpreter
from features.hepatology import calculate_all_scores
from features.narrative_generation import NarrativeComposer
from models.organ_models import evaluate_all_organs
from inference.monitoring import RealTimeMonitor

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


class MIMICBatchScorer:
    """Score MIMIC cohorts in batch, generating structured outputs."""

    def __init__(self, output_dir: str | Path = "mimic_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.monitor = RealTimeMonitor(baseline_model_auc=0.75)

    def score_patient(self, patient_id: str, labs: Dict[str, Optional[float]]) -> Dict:
        """Score a single patient across all 5 phases.

        Returns structured result dict.
        """
        # Phase 1: Differential diagnosis
        interpreter = LabInterpreter(enrich=False)
        ddx = interpreter.differential(labs, max_items=6)
        differentials = [
            {
                "condition": item.condition,
                "priority": item.priority,
                "rationale": item.rationale,
                "supporting": list(item.supporting),
            }
            for item in ddx
        ]

        # Phase 2: Hepatology
        hep_scores = calculate_all_scores(labs)
        hepatology = {}
        for name, score in hep_scores.items():
            if score:
                hepatology[name] = {
                    "score": float(score.value),
                    "interpretation": score.interpretation,
                    "confidence": score.confidence,
                }

        # Phase 3: Organ models
        organ_risks = evaluate_all_organs(labs)
        organ_assessment = {}
        for organ, score in organ_risks.items():
            if score:
                organ_assessment[organ] = {
                    "system": score.system,
                    "condition": score.condition,
                    "risk_score": float(score.risk_score),
                    "risk_category": score.risk_category,
                    "key_findings": score.key_findings,
                }

        # Phase 4: Monitoring (track worst-case organ risk as deterioration)
        worst_risk = max(
            [s.risk_score for s in organ_risks.values() if s], default=0.0
        )
        monitoring_result = self.monitor.process_prediction(
            patient_id=patient_id,
            predicted_risk=worst_risk,
            alert_type="deterioration",
            key_findings=[
                f"{s.system}: {s.risk_category}"
                for s in organ_risks.values()
                if s
            ],
        )

        monitoring = {
            "worst_organ_risk": float(worst_risk),
            "alert_generated": monitoring_result["risk_alert"] is not None,
        }
        if monitoring_result["risk_alert"]:
            monitoring["alert_text"] = monitoring_result["risk_alert"].recommendation

        # Phase 5: Narrative
        composer = NarrativeComposer()
        narrative = composer.compose(labs)
        narrative_result = {
            "summary": narrative.summary,
            "key_abnormalities": narrative.key_abnormalities,
            "concern_areas": narrative.concern_areas,
            "recommendation": narrative.recommendation,
        }

        return {
            "patient_id": patient_id,
            "timestamp": datetime.now().isoformat(),
            "phase1_differential": differentials,
            "phase2_hepatology": hepatology,
            "phase3_organ_risk": organ_assessment,
            "phase4_monitoring": monitoring,
            "phase5_narrative": narrative_result,
        }

    def score_cohort(self, cohort: pd.DataFrame, batch_size: int = 1000) -> pd.DataFrame:
        """Score entire cohort, returning summary DataFrame.

        Args:
            cohort: DataFrame with lab columns (lab_* prefix)
            batch_size: Rows per batch for memory management

        Returns:
            Summary DataFrame with key metrics per patient
        """
        results = []
        total = len(cohort)

        logger.info(f"Scoring {total} patients...")

        for batch_idx in range(0, total, batch_size):
            batch = cohort.iloc[batch_idx : batch_idx + batch_size]
            batch_num = batch_idx // batch_size + 1
            total_batches = (total + batch_size - 1) // batch_size

            logger.info(f"  Batch {batch_num}/{total_batches}...")

            for idx, row in batch.iterrows():
                patient_id = str(row.get("patient_id", idx))
                labs = {
                    col.replace("lab_", ""): row[col]
                    for col in row.index
                    if col.startswith("lab_") and pd.notna(row[col])
                }

                if not labs:
                    continue

                full_result = self.score_patient(patient_id, labs)

                # Extract summary metrics
                summary = {
                    "patient_id": patient_id,
                    "n_differentials": len(full_result["phase1_differential"]),
                    "top_differential": full_result["phase1_differential"][0][
                        "condition"
                    ]
                    if full_result["phase1_differential"]
                    else None,
                    "n_hepatology_scores": len(full_result["phase2_hepatology"]),
                    "worst_hepatology": (
                        max(
                            [s["score"] for s in full_result["phase2_hepatology"].values()]
                        )
                        if full_result["phase2_hepatology"]
                        else None
                    ),
                    "n_organs_at_risk": len(full_result["phase3_organ_risk"]),
                    "worst_organ_risk": full_result["phase4_monitoring"][
                        "worst_organ_risk"
                    ],
                    "worst_organ_system": (
                        max(
                            full_result["phase3_organ_risk"].items(),
                            key=lambda x: x[1]["risk_score"],
                        )[0]
                        if full_result["phase3_organ_risk"]
                        else None
                    ),
                    "alert_generated": full_result["phase4_monitoring"]["alert_generated"],
                    "n_concern_areas": len(full_result["phase5_narrative"]["concern_areas"]),
                }
                results.append(summary)

                # Save full result every 100 patients
                if len(results) % 100 == 0:
                    self._save_batch_results(results[-100:])

        results_df = pd.DataFrame(results)
        logger.info(f"Scored {len(results_df)} patients successfully")
        return results_df

    def _save_batch_results(self, batch: List[Dict]) -> None:
        """Save batch of results to JSON."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        outfile = self.output_dir / f"batch_{timestamp}.jsonl"
        with open(outfile, "a") as f:
            for result in batch:
                f.write(json.dumps(result) + "\n")

    def generate_report(self, results_df: pd.DataFrame) -> str:
        """Generate summary statistics report."""
        report = []
        report.append("=" * 80)
        report.append("MIMIC-IV BATCH SCORING REPORT")
        report.append("=" * 80)
        report.append(f"\nPatients scored: {len(results_df)}")
        report.append(f"Timestamp: {datetime.now().isoformat()}\n")

        report.append("DIFFERENTIAL DIAGNOSIS:")
        report.append(
            f"  • Mean differentials per patient: {results_df['n_differentials'].mean():.1f}"
        )
        report.append(
            f"  • Top condition: {results_df['top_differential'].value_counts().head(1).to_dict()}"
        )

        report.append("\nHEPATOLOGY:")
        report.append(
            f"  • Patients with scores: {(results_df['n_hepatology_scores'] > 0).sum()} ({(results_df['n_hepatology_scores'] > 0).sum() / len(results_df) * 100:.1f}%)"
        )
        report.append(
            f"  • Mean worst score: {results_df['worst_hepatology'].mean():.2f}"
        )

        report.append("\nORGAN-SYSTEM RISK:")
        report.append(
            f"  • Patients with ≥1 organ at risk: {(results_df['n_organs_at_risk'] > 0).sum()} ({(results_df['n_organs_at_risk'] > 0).sum() / len(results_df) * 100:.1f}%)"
        )
        report.append(
            f"  • Mean worst organ risk: {results_df['worst_organ_risk'].mean():.2%}"
        )
        report.append(
            f"  • Most common at-risk organ: {results_df['worst_organ_system'].value_counts().head(1).to_dict()}"
        )

        report.append("\nALERTS:")
        report.append(
            f"  • Patients with alert: {results_df['alert_generated'].sum()} ({results_df['alert_generated'].sum() / len(results_df) * 100:.1f}%)"
        )

        report.append("\nCONCERN AREAS:")
        report.append(
            f"  • Mean concern areas per patient: {results_df['n_concern_areas'].mean():.1f}"
        )

        report.append("\n" + "=" * 80)
        return "\n".join(report)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python batch_score_mimic.py <path_to_cohort_csv> [output_dir]")
        print("\nExample:")
        print("  python batch_score_mimic.py ./mimic_cohort.csv ./results")
        sys.exit(1)

    cohort_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "mimic_results"

    logger.info(f"Loading cohort from {cohort_path}...")
    cohort = pd.read_csv(cohort_path)

    scorer = MIMICBatchScorer(output_dir=output_dir)
    results = scorer.score_cohort(cohort)

    # Save results
    results_file = Path(output_dir) / "summary_results.csv"
    results.to_csv(results_file, index=False)
    logger.info(f"Results saved to {results_file}")

    # Print report
    report = scorer.generate_report(results)
    print(report)

    report_file = Path(output_dir) / "report.txt"
    with open(report_file, "w") as f:
        f.write(report)
    logger.info(f"Report saved to {report_file}")
