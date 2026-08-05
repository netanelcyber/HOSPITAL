"""Validation script: compare predictions across cohorts and validate against outcomes.

Cross-validates model performance:
- Across MIMIC-III, MIMIC-IV, eICU cohorts
- Against known outcomes (deterioration, mortality, readmission)
- Calibration, discrimination, decision curves
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json

import numpy as np
import pandas as pd
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    roc_curve,
    precision_recall_curve,
    brier_score_loss,
    calibration_curve,
)
import matplotlib.pyplot as plt

from features.lab_interpretation import LabInterpreter
from models.organ_models import evaluate_all_organs

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


class PredictionValidator:
    """Validates predictions against ground truth outcomes."""

    def __init__(self, output_dir: str | Path = "validation_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def load_cohort_with_outcomes(
        self, csv_path: str | Path
    ) -> Tuple[pd.DataFrame, np.ndarray]:
        """Load cohort and extract outcome variable.

        Expected columns:
        - lab_* (lab values)
        - deteriorated (binary outcome) OR
        - mortality (binary outcome) OR
        - readmitted (binary outcome)
        """
        df = pd.read_csv(csv_path)

        # Identify outcome column
        outcome_col = None
        for col in ["deteriorated", "mortality", "readmitted", "died", "outcome"]:
            if col in df.columns:
                outcome_col = col
                break

        if not outcome_col:
            raise ValueError(
                "No outcome column found. Expected: deteriorated, mortality, readmitted"
            )

        y = df[outcome_col].fillna(0).astype(int).values
        return df, y

    def score_cohort(self, cohort: pd.DataFrame) -> np.ndarray:
        """Score cohort, returning deterioration risk per patient.

        Uses worst organ-system risk as main deterioration score.
        """
        scores = []

        for idx, row in cohort.iterrows():
            labs = {
                col.replace("lab_", ""): row[col]
                for col in row.index
                if col.startswith("lab_") and pd.notna(row[col])
            }

            if not labs:
                scores.append(0.0)
                continue

            organ_risks = evaluate_all_organs(labs)
            organ_risk_values = [s.risk_score for s in organ_risks.values() if s]
            risk = max(organ_risk_values) if organ_risk_values else 0.0
            scores.append(risk)

        return np.array(scores)

    def compute_metrics(
        self, y_true: np.ndarray, y_pred: np.ndarray, name: str = "Model"
    ) -> Dict:
        """Compute comprehensive evaluation metrics."""
        metrics = {
            "name": name,
            "n_samples": len(y_true),
            "n_events": int(y_true.sum()),
            "event_rate": float(y_true.mean()),
        }

        # Discrimination
        if len(np.unique(y_true)) > 1:
            metrics["roc_auc"] = float(roc_auc_score(y_true, y_pred))
            metrics["avg_precision"] = float(average_precision_score(y_true, y_pred))
        else:
            metrics["roc_auc"] = None
            metrics["avg_precision"] = None

        # Calibration
        metrics["brier_score"] = float(brier_score_loss(y_true, y_pred))

        # Threshold performance
        if len(np.unique(y_true)) > 1:
            for threshold in [0.1, 0.3, 0.5, 0.7]:
                y_pred_binary = (y_pred >= threshold).astype(int)
                tp = ((y_pred_binary == 1) & (y_true == 1)).sum()
                fp = ((y_pred_binary == 1) & (y_true == 0)).sum()
                fn = ((y_pred_binary == 0) & (y_true == 1)).sum()

                sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0
                specificity = (len(y_true) - fp - fn) / (len(y_true) - (tp + fn)) if (len(y_true) - tp - fn) > 0 else 0
                ppv = tp / (tp + fp) if (tp + fp) > 0 else 0

                metrics[f"sensitivity_{int(threshold*100)}%_alert"] = float(sensitivity)
                metrics[f"ppv_{int(threshold*100)}%_alert"] = float(ppv)

        return metrics

    def validate_cohort(
        self, csv_path: str | Path, cohort_name: str
    ) -> Dict:
        """Validate predictions on a cohort.

        Args:
            csv_path: Path to cohort CSV with outcomes
            cohort_name: Name for results (e.g., "MIMIC-IV")

        Returns:
            Dict of metrics and plots
        """
        logger.info(f"Validating {cohort_name}...")

        cohort, y_true = self.load_cohort_with_outcomes(csv_path)
        logger.info(f"  Loaded {len(cohort)} stays, {y_true.sum()} events")

        y_pred = self.score_cohort(cohort)
        logger.info(f"  Scored all patients")

        metrics = self.compute_metrics(y_true, y_pred, name=cohort_name)

        # Generate plots
        self._plot_roc_curve(y_true, y_pred, cohort_name)
        self._plot_calibration(y_true, y_pred, cohort_name)
        self._plot_score_distribution(y_true, y_pred, cohort_name)

        logger.info(f"\n{cohort_name} Results:")
        for key, val in metrics.items():
            if isinstance(val, float):
                logger.info(f"  {key}: {val:.3f}")
            else:
                logger.info(f"  {key}: {val}")

        return {
            "metrics": metrics,
            "y_true": y_true,
            "y_pred": y_pred,
        }

    def _plot_roc_curve(
        self, y_true: np.ndarray, y_pred: np.ndarray, name: str
    ) -> None:
        """Plot ROC curve."""
        if len(np.unique(y_true)) < 2:
            return

        fpr, tpr, _ = roc_curve(y_true, y_pred)
        auc = roc_auc_score(y_true, y_pred)

        plt.figure(figsize=(8, 6))
        plt.plot(fpr, tpr, label=f"{name} (AUC={auc:.3f})", linewidth=2)
        plt.plot([0, 1], [0, 1], "k--", alpha=0.3, label="Random")
        plt.xlabel("False Positive Rate")
        plt.ylabel("True Positive Rate")
        plt.title(f"ROC Curve — {name}")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.output_dir / f"roc_{name.replace(' ', '_').lower()}.png", dpi=100)
        plt.close()
        logger.info(f"  Saved: roc_{name.lower()}.png")

    def _plot_calibration(
        self, y_true: np.ndarray, y_pred: np.ndarray, name: str
    ) -> None:
        """Plot calibration curve."""
        prob_true, prob_pred = calibration_curve(
            y_true, y_pred, n_bins=10, strategy="uniform"
        )

        plt.figure(figsize=(8, 6))
        plt.plot(prob_pred, prob_true, "o-", label=name, linewidth=2, markersize=6)
        plt.plot([0, 1], [0, 1], "k--", alpha=0.3, label="Perfect calibration")
        plt.xlabel("Mean Predicted Probability")
        plt.ylabel("Fraction of Positives")
        plt.title(f"Calibration Curve — {name}")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.xlim(-0.05, 1.05)
        plt.ylim(-0.05, 1.05)
        plt.tight_layout()
        plt.savefig(self.output_dir / f"calibration_{name.replace(' ', '_').lower()}.png", dpi=100)
        plt.close()
        logger.info(f"  Saved: calibration_{name.lower()}.png")

    def _plot_score_distribution(
        self, y_true: np.ndarray, y_pred: np.ndarray, name: str
    ) -> None:
        """Plot distribution of predictions by outcome."""
        plt.figure(figsize=(10, 6))
        plt.hist(y_pred[y_true == 0], bins=30, alpha=0.6, label="No event", color="blue")
        plt.hist(y_pred[y_true == 1], bins=30, alpha=0.6, label="Event", color="red")
        plt.xlabel("Predicted Risk")
        plt.ylabel("Frequency")
        plt.title(f"Score Distribution — {name}")
        plt.legend()
        plt.grid(True, alpha=0.3, axis="y")
        plt.tight_layout()
        plt.savefig(self.output_dir / f"distribution_{name.replace(' ', '_').lower()}.png", dpi=100)
        plt.close()
        logger.info(f"  Saved: distribution_{name.lower()}.png")

    def compare_cohorts(self, cohort_paths: Dict[str, str]) -> pd.DataFrame:
        """Compare performance across multiple cohorts.

        Args:
            cohort_paths: {"MIMIC-IV": "/path/to/mimic_iv.csv", ...}

        Returns:
            Comparison DataFrame
        """
        results = {}

        for name, path in cohort_paths.items():
            try:
                result = self.validate_cohort(path, name)
                results[name] = result["metrics"]
            except Exception as e:
                logger.error(f"Failed to validate {name}: {e}")

        comparison_df = pd.DataFrame(results).T
        comparison_file = self.output_dir / "comparison.csv"
        comparison_df.to_csv(comparison_file)
        logger.info(f"\nComparison saved: {comparison_file}")

        return comparison_df

    def generate_validation_report(self, results: Dict) -> str:
        """Generate human-readable validation report."""
        report = []
        report.append("=" * 80)
        report.append("PREDICTION VALIDATION REPORT")
        report.append("=" * 80)

        for cohort_name, data in results.items():
            metrics = data["metrics"]
            report.append(f"\n{cohort_name}:")
            report.append(f"  Patients: {metrics['n_samples']:,}")
            report.append(f"  Events: {metrics['n_events']} ({metrics['event_rate']:.1%})")
            if metrics["roc_auc"]:
                report.append(f"  AUC-ROC: {metrics['roc_auc']:.3f}")
                report.append(f"  AUC-PR: {metrics['avg_precision']:.3f}")
            report.append(f"  Brier: {metrics['brier_score']:.3f}")

        report.append("\n" + "=" * 80)
        return "\n".join(report)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python validate_predictions.py <cohort_csv> [cohort_name]")
        print("\nExample:")
        print("  python validate_predictions.py ./mimic_iv_outcomes.csv MIMIC-IV")
        print("\nExpected CSV columns:")
        print("  • lab_* (lab values)")
        print("  • deteriorated or mortality or readmitted (0/1 outcome)")
        print("\nOutputs:")
        print("  • ROC curves")
        print("  • Calibration plots")
        print("  • Score distributions")
        print("  • Metrics summary")
        sys.exit(1)

    csv_path = sys.argv[1]
    cohort_name = sys.argv[2] if len(sys.argv) > 2 else "Cohort"

    validator = PredictionValidator(output_dir="validation_results")
    result = validator.validate_cohort(csv_path, cohort_name)

    report = validator.generate_validation_report({cohort_name: result})
    print(report)

    report_file = Path("validation_results") / "report.txt"
    with open(report_file, "w") as f:
        f.write(report)
    print(f"\nReport saved: {report_file}")
