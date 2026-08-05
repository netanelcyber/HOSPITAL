"""Organ-system-specific prediction models.

Each model predicts risk within a specific organ system:
- Cardiac: MI, heart failure, arrhythmia
- Renal: AKI progression, KDIGO staging
- Sepsis: Sepsis risk, septic shock
- Pulmonary: Respiratory failure, hypoxia
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrganRiskScore:
    """Risk score for an organ system."""

    system: str
    condition: str
    risk_score: float  # 0.0 to 1.0 (probability)
    risk_category: str  # "low", "moderate", "high", "critical"
    key_findings: List[str]  # Which labs drove the score


def categorize_risk(score: float, low_threshold: float = 0.1,
                    moderate_threshold: float = 0.3, high_threshold: float = 0.7) -> str:
    """Convert numerical risk score to category."""
    if score < low_threshold:
        return "low"
    elif score < moderate_threshold:
        return "moderate"
    elif score < high_threshold:
        return "high"
    else:
        return "critical"


class CardiacRiskModel:
    """Predict acute coronary syndrome and heart failure risk.

    Uses troponin, BNP, electrolytes, and metabolic markers.
    """

    def __init__(self):
        self.fitted = False
        self._feature_names = ["troponin_i", "bnp", "potassium", "calcium", "glucose", "lactate"]

    def predict(self, labs: Dict[str, Optional[float]]) -> Optional[OrganRiskScore]:
        """Predict cardiac risk without a trained model.

        For now, uses rule-based heuristics pending model training on MIMIC cardiac cohorts.
        """
        key_findings = []
        score_components = []

        # Troponin elevation → MI risk
        troponin = labs.get("troponin_i") or labs.get("troponin_t")
        if troponin and troponin > 0.04:
            key_findings.append(f"Elevated troponin ({troponin:.2f})")
            score_components.append(min(0.9, (troponin - 0.04) / 0.2))

        # BNP elevation → HF risk
        bnp = labs.get("bnp") or labs.get("nt_probnp")
        if bnp and bnp > 100:
            key_findings.append(f"Elevated BNP ({bnp:.0f})")
            score_components.append(min(0.7, (bnp - 100) / 500))

        # Electrolyte derangement → arrhythmia risk
        k = labs.get("potassium")
        ca = labs.get("calcium")
        if (k and (k < 3.0 or k > 6.0)) or (ca and (ca < 7.0 or ca > 11.0)):
            key_findings.append("Dangerous electrolyte derangement (arrhythmia risk)")
            score_components.append(0.5)

        # Lactate → shock risk
        lactate = labs.get("lactate")
        if lactate and lactate > 2.0:
            key_findings.append(f"Elevated lactate ({lactate:.1f}); tissue hypoperfusion")
            score_components.append(min(0.6, lactate / 5))

        if not score_components:
            return None

        risk_score = float(np.mean(score_components))
        risk_category = categorize_risk(risk_score)

        return OrganRiskScore(
            system="Cardiac",
            condition="Acute coronary syndrome / heart failure",
            risk_score=risk_score,
            risk_category=risk_category,
            key_findings=key_findings,
        )


class RenalRiskModel:
    """Predict AKI progression and KDIGO staging.

    Uses creatinine trend, BUN, potassium, and pH.
    """

    @staticmethod
    def compute_kdigo_stage(
        creatinine_now: Optional[float],
        creatinine_baseline: Optional[float] = 0.8,
        urine_output_ml_kg_day: Optional[float] = None,
    ) -> Optional[str]:
        """KDIGO AKI staging based on creatinine rise.

        Stage 1: 1.5-1.9x baseline or ≥0.3 mg/dL rise
        Stage 2: 2.0-2.9x baseline
        Stage 3: ≥3.0x baseline or ≥4.0 mg/dL (if rise from baseline <0.5)

        Args:
            creatinine_now: Current serum creatinine, mg/dL
            creatinine_baseline: Baseline (assume ~0.8 if unknown)
            urine_output_ml_kg_day: Output per kg/day (0.5-2 mL/kg/day indicates progressive AKI)

        Returns:
            "1", "2", "3", or None if insufficient data
        """
        if creatinine_now is None or creatinine_baseline is None:
            return None

        if creatinine_baseline <= 0:
            return None

        ratio = creatinine_now / creatinine_baseline
        absolute_rise = creatinine_now - creatinine_baseline

        if ratio >= 3.0 or creatinine_now >= 4.0:
            return "3"
        elif ratio >= 2.0:
            return "2"
        elif ratio >= 1.5 or absolute_rise >= 0.3:
            return "1"
        else:
            return None

    def predict(
        self,
        labs: Dict[str, Optional[float]],
        creatinine_baseline: Optional[float] = None,
    ) -> Optional[OrganRiskScore]:
        """Predict AKI risk and staging."""
        key_findings = []
        score = 0.0

        cr_now = labs.get("creatinine")
        if cr_now is None:
            return None

        # Infer baseline if not provided (heuristic)
        if creatinine_baseline is None:
            creatinine_baseline = 0.8 if cr_now < 1.5 else 1.1

        stage = self.compute_kdigo_stage(cr_now, creatinine_baseline)
        if stage:
            key_findings.append(f"KDIGO AKI Stage {stage}")
            score += float(stage) / 3.0

        # Urea to creatinine ratio (BUN/Cr > 20 suggests prerenal)
        bun = labs.get("blood_urea_nitrogen")
        if bun and cr_now:
            ratio = bun / cr_now
            if ratio > 20:
                key_findings.append("Elevated BUN/Cr ratio (prerenal pattern)")
                score = min(1.0, score + 0.3)
            elif ratio > 10:
                key_findings.append("Mild BUN/Cr elevation")

        # Hyperkalemia in AKI (dangerous)
        k = labs.get("potassium")
        if k and k > 5.5:
            key_findings.append(f"Hyperkalemia ({k:.1f}) with renal dysfunction")
            score = min(1.0, score + 0.4)

        # Metabolic acidosis with AKI
        ph = labs.get("ph")
        if ph and ph < 7.30:
            key_findings.append("Metabolic acidosis (pH < 7.30)")
            score = min(1.0, score + 0.2)

        if not key_findings:
            return None

        risk_category = categorize_risk(float(score))

        return OrganRiskScore(
            system="Renal",
            condition=f"Acute kidney injury (Stage {stage})" if stage else "AKI risk",
            risk_score=float(score),
            risk_category=risk_category,
            key_findings=key_findings,
        )


class SepsisRiskModel:
    """Predict sepsis and septic shock risk.

    Uses WBC, lactate, procalcitonin, platelet count, and organ markers.
    """

    def predict(self, labs: Dict[str, Optional[float]]) -> Optional[OrganRiskScore]:
        """Predict sepsis risk using inflammatory and hypoperfusion markers."""
        key_findings = []
        score_components = []

        # Lactate is the strongest predictor
        lactate = labs.get("lactate")
        if lactate and lactate > 1.0:
            key_findings.append(f"Elevated lactate ({lactate:.1f}); tissue hypoperfusion")
            score_components.append(min(0.9, lactate / 4.0))

        # Leukocytosis with left shift (approximated by WBC alone)
        wbc = labs.get("white_blood_cell_count")
        if wbc and (wbc < 4.0 or wbc > 11.0):
            if wbc > 11:
                key_findings.append(f"Leukocytosis ({wbc:.1f})")
                score_components.append(min(0.4, (wbc - 11) / 10))
            else:
                key_findings.append(f"Leukopenia ({wbc:.1f}); immune risk")
                score_components.append(0.35)

        # Procalcitonin (if available; better than CRP for bacteria)
        pct = labs.get("procalcitonin")
        if pct and pct > 0.5:
            key_findings.append(f"Elevated procalcitonin ({pct:.2f}); likely bacterial infection")
            score_components.append(min(0.8, pct / 2.0))

        # Thrombocytopenia (platelet consumption in severe sepsis)
        plt = labs.get("platelet_count")
        if plt and plt < 100:
            key_findings.append(f"Thrombocytopenia ({plt:.0f}); coagulation activation")
            score_components.append(min(0.7, (100 - plt) / 150))

        # Creatinine elevation (organ dysfunction)
        cr = labs.get("creatinine")
        if cr and cr > 1.5:
            key_findings.append(f"Elevated creatinine ({cr:.1f}); AKI/organ stress")
            score_components.append(min(0.5, (cr - 1.3) / 2.0))

        # Hyperglycemia in non-diabetics (stress response)
        glucose = labs.get("glucose")
        if glucose and glucose > 150:
            key_findings.append(f"Hyperglycemia ({glucose:.0f}); stress response")
            score_components.append(min(0.3, (glucose - 150) / 100))

        if not score_components:
            return None

        risk_score = float(np.mean(score_components))

        # Septic shock if lactate > 2 AND hypotension markers
        if lactate and lactate > 2.0:
            risk_category = "critical" if risk_score > 0.7 else "high"
        else:
            risk_category = categorize_risk(risk_score)

        return OrganRiskScore(
            system="Sepsis/Infection",
            condition="Sepsis / septic shock",
            risk_score=risk_score,
            risk_category=risk_category,
            key_findings=key_findings,
        )


class PulmonaryRiskModel:
    """Predict respiratory failure and hypoxia risk.

    Uses pO2 (if available), lactate, pH, and other markers of gas exchange failure.
    """

    def predict(self, labs: Dict[str, Optional[float]]) -> Optional[OrganRiskScore]:
        """Predict pulmonary/respiratory failure risk."""
        key_findings = []
        score_components = []

        # Hypoxemia (pO2 < 60 is severe)
        po2 = labs.get("po2")
        if po2 and po2 < 75:
            key_findings.append(f"Hypoxemia (pO2 {po2:.0f})")
            score_components.append(min(0.9, (75 - po2) / 20))

        # Hypercapnia (pCO2 > 45 indicates CO2 retention)
        pco2 = labs.get("pco2")
        if pco2 and pco2 > 45:
            key_findings.append(f"Hypercapnia (pCO2 {pco2:.0f}); respiratory failure")
            score_components.append(min(0.8, (pco2 - 45) / 20))

        # Respiratory acidosis (low pH + high pCO2)
        ph = labs.get("ph")
        if ph and ph < 7.30:
            key_findings.append(f"Severe acidosis (pH {ph:.2f})")
            score_components.append(min(0.7, (7.35 - ph) / 0.1))

        # Lactate (tissue hypoxia from poor gas exchange)
        lactate = labs.get("lactate")
        if lactate and lactate > 2.0:
            key_findings.append(f"Elevated lactate ({lactate:.1f}); tissue hypoxia")
            score_components.append(min(0.6, lactate / 4.0))

        # Leukocytosis suggesting infection/ARDS
        wbc = labs.get("white_blood_cell_count")
        if wbc and wbc > 12.0:
            key_findings.append(f"Leukocytosis ({wbc:.1f}); inflammatory response")
            score_components.append(0.3)

        if not score_components:
            return None

        risk_score = float(np.mean(score_components))
        risk_category = categorize_risk(risk_score)

        return OrganRiskScore(
            system="Pulmonary",
            condition="Respiratory failure / acute respiratory distress",
            risk_score=risk_score,
            risk_category=risk_category,
            key_findings=key_findings,
        )


def evaluate_all_organs(labs: Dict[str, Optional[float]]) -> Dict[str, Optional[OrganRiskScore]]:
    """Evaluate risk across all organ systems."""
    return {
        "cardiac": CardiacRiskModel().predict(labs),
        "renal": RenalRiskModel().predict(labs),
        "sepsis": SepsisRiskModel().predict(labs),
        "pulmonary": PulmonaryRiskModel().predict(labs),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Example: critically ill patient
    panel = {
        "troponin_i": 0.15,
        "bnp": 800,
        "potassium": 5.8,
        "calcium": 7.2,
        "glucose": 240,
        "lactate": 3.2,
        "creatinine": 2.8,
        "blood_urea_nitrogen": 68,
        "white_blood_cell_count": 18.5,
        "procalcitonin": 2.1,
        "platelet_count": 85,
        "po2": 55,
        "pco2": 52,
        "ph": 7.22,
    }

    print("Organ System Risk Assessment:")
    scores = evaluate_all_organs(panel)
    for organ, score in scores.items():
        if score:
            print(f"\n{score.system}: {score.risk_category.upper()}")
            print(f"  Risk: {score.risk_score:.2%}")
            print(f"  Condition: {score.condition}")
            print(f"  Key findings:")
            for finding in score.key_findings:
                print(f"    - {finding}")
