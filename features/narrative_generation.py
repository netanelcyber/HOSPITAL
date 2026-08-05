"""Generate clinical narratives from abnormal lab patterns.

Produces readable summaries that clinicians can review. Uses rule-based
composition (not LLM) to remain auditable and deterministic.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClinicalNarrative:
    """Structured clinical summary from lab interpretation."""

    summary: str
    key_abnormalities: List[str]
    concern_areas: List[str]  # organ systems at risk
    recommendation: str
    caveats: List[str]


class NarrativeComposer:
    """Compose clinical narratives from lab panels."""

    # Template library for common patterns
    TEMPLATES = {
        "renal_injury": (
            "Markers of acute kidney injury: {creatinine} mg/dL (baseline ~{baseline}) "
            "with blood urea nitrogen {bun} mg/dL. "
            "The BUN/Cr ratio of {ratio:.1f} {pattern}. "
            "{recommendation}"
        ),
        "electrolyte_risk": (
            "Critical electrolyte derangement with potassium {k} mmol/L and "
            "sodium {na} mmol/L creates arrhythmia risk. "
            "{recommendation}"
        ),
        "liver_injury": (
            "Evidence of hepatocellular injury: AST {ast} U/L, ALT {alt} U/L "
            "(ratio {ratio:.2f}), bilirubin {bili} mg/dL, albumin {alb} g/dL. "
            "{pattern}. {recommendation}"
        ),
        "coagulation": (
            "Coagulation derangement: PT {pt:.1f} sec (INR {inr:.2f}), "
            "platelets {plt} K/uL, fibrinogen {fib} mg/dL. "
            "{severity}. {recommendation}"
        ),
        "infection": (
            "Evidence of systemic infection: WBC {wbc} K/uL, "
            "procalcitonin {pct:.2f} ng/mL, lactate {lactate:.1f} mmol/L. "
            "{severity}. {recommendation}"
        ),
        "hypoxia": (
            "Gas exchange impairment: pO2 {po2} mmHg (FiO2 assumption 0.21), "
            "pCO2 {pco2} mmHg, pH {ph:.2f}, lactate {lactate:.1f}. "
            "{severity}. {recommendation}"
        ),
    }

    def __init__(self):
        pass

    def assess_renal_function(self, labs: Dict[str, Optional[float]]) -> Optional[str]:
        """Assess and describe renal status."""
        cr = labs.get("creatinine")
        bun = labs.get("blood_urea_nitrogen")
        baseline_cr = 0.8

        if not cr or not bun:
            return None

        ratio = bun / cr

        if cr > 3.0:
            severity = "severe acute kidney injury"
        elif cr > 1.5:
            severity = "acute kidney injury"
        else:
            return None  # Not concerning

        if ratio > 20:
            pattern = "suggests prerenal etiology (volume depletion)"
        elif ratio > 10:
            pattern = "mild elevation suggests mixed pattern"
        else:
            pattern = "suggests intrinsic renal disease"

        return self.TEMPLATES["renal_injury"].format(
            creatinine=cr,
            baseline=baseline_cr,
            bun=bun,
            ratio=ratio,
            pattern=pattern,
            recommendation=(
                "Clinical correlation needed: assess urine output, central venous pressure, "
                "and volume status to differentiate causes."
            ),
        )

    def assess_liver_function(self, labs: Dict[str, Optional[float]]) -> Optional[str]:
        """Assess and describe liver status."""
        ast = labs.get("aspartate_aminotransferase")
        alt = labs.get("alanine_aminotransferase")
        bili = labs.get("bilirubin")
        alb = labs.get("albumin")
        inr = labs.get("inr")

        if not all([ast, alt, bili, alb]):
            return None

        ratio = ast / alt if alt > 0 else 0

        if bili > 3.0 and inr > 1.5:
            severity = "severe"
            pattern = "Marked hyperbilirubinemia with coagulopathy suggests acute liver failure"
        elif bili > 2.0:
            severity = "moderate"
            pattern = "Significant hyperbilirubinemia; hepatocellular or cholestatic pattern"
        elif ast > 300 or alt > 300:
            severity = "acute"
            pattern = "Acute transaminitis; viral hepatitis, toxin, or ischemia to consider"
        else:
            pattern = "Mild elevation; follow trend"

        recommendation = (
            "Check viral serology (A, B, C), acetaminophen level, autoimmune markers. "
            "Ultrasound to assess for cirrhosis stigmata or portal hypertension."
        )

        return self.TEMPLATES["liver_injury"].format(
            ast=int(ast),
            alt=int(alt),
            ratio=ratio,
            bili=bili,
            alb=alb,
            pattern=pattern,
            recommendation=recommendation,
        )

    def assess_coagulation(self, labs: Dict[str, Optional[float]]) -> Optional[str]:
        """Assess and describe coagulation status."""
        pt = labs.get("prothrombin_time")
        inr = labs.get("inr")
        ptt = labs.get("partial_thromboplastin_time")
        plt = labs.get("platelet_count")
        fib = labs.get("fibrinogen") or 250  # estimate if missing

        abnormalities = []
        if pt and pt > 13.5:
            abnormalities.append("PT prolonged")
        if ptt and ptt > 35:
            abnormalities.append("PTT prolonged")
        if plt and plt < 100:
            abnormalities.append("thrombocytopenia")

        if not abnormalities:
            return None

        if plt and plt < 50:
            severity = "CRITICAL thrombocytopenia"
            rec = "Consider DIC workup (fibrinogen, D-dimer, LDH). Transfusion threshold may be lower."
        elif inr and inr > 2.0:
            severity = "Coagulopathy with increased bleeding risk"
            rec = "Check liver function, vitamin K levels. Consider FFP vs reversal agents if bleeding."
        else:
            severity = "Mild coagulation abnormality"
            rec = "Repeat testing to confirm; assess for underlying cause."

        return self.TEMPLATES["coagulation"].format(
            pt=pt or 13,
            inr=inr or 1.0,
            plt=plt or 200,
            fib=int(fib),
            severity=severity,
            recommendation=rec,
        )

    def assess_infection(self, labs: Dict[str, Optional[float]]) -> Optional[str]:
        """Assess and describe infection risk."""
        wbc = labs.get("white_blood_cell_count")
        pct = labs.get("procalcitonin")
        lactate = labs.get("lactate")
        crp = labs.get("c_reactive_protein")

        if not any([wbc, pct, lactate]):
            return None

        # Determine severity
        if lactate and lactate > 2.0:
            severity = "SEPSIS SUSPECTED: Elevated lactate indicates tissue hypoperfusion"
        elif pct and pct > 1.0:
            severity = "Likely bacterial infection (procalcitonin > 1.0)"
        elif wbc and wbc > 15:
            severity = "Marked leukocytosis"
        else:
            return None

        recommendation = (
            "Obtain blood cultures if febrile. Consider empiric antibiotics if "
            "sepsis criteria met. Source control and fluid resuscitation if septic shock."
        )

        return self.TEMPLATES["infection"].format(
            wbc=wbc or 7,
            pct=pct or 0.1,
            lactate=lactate or 1.0,
            severity=severity,
            recommendation=recommendation,
        )

    def assess_gas_exchange(self, labs: Dict[str, Optional[float]]) -> Optional[str]:
        """Assess and describe gas exchange and acid-base status."""
        po2 = labs.get("po2")
        pco2 = labs.get("pco2")
        ph = labs.get("ph")
        bicab = labs.get("bicarbonate")
        lactate = labs.get("lactate")

        abnormalities = []
        if po2 and po2 < 80:
            abnormalities.append("hypoxemia")
        if pco2 and pco2 > 45:
            abnormalities.append("hypercapnia")
        if ph and ph < 7.35:
            abnormalities.append("acidemia")

        if not abnormalities:
            return None

        if ph and ph < 7.20:
            severity = "SEVERE ACIDOSIS: Urgent intervention needed"
        elif po2 and po2 < 60:
            severity = "SEVERE HYPOXEMIA: Respiratory failure likely"
        else:
            severity = "Gas exchange impairment"

        recommendation = (
            "Check oxygen delivery (SpO2, hemoglobin), ventilation adequacy (pCO2). "
            "Assess for ARDS, aspiration, PE, or other parenchymal disease. "
            "Consider mechanical ventilation if worsening."
        )

        return self.TEMPLATES["hypoxia"].format(
            po2=po2 or 90,
            pco2=pco2 or 40,
            ph=ph or 7.40,
            lactate=lactate or 1.0,
            severity=severity,
            recommendation=recommendation,
        )

    def compose(self, labs: Dict[str, Optional[float]]) -> ClinicalNarrative:
        """Generate a full clinical narrative from labs."""
        narratives = []
        key_abnormalities = []
        concern_areas = []
        caveats = [
            "Laboratory interpretation is not a diagnosis.",
            "Clinical judgment must supersede any automated summary.",
            "Physical examination and imaging are essential for diagnosis.",
        ]

        # Assess each organ system
        renal = self.assess_renal_function(labs)
        if renal:
            narratives.append(renal)
            key_abnormalities.append(f"Creatinine {labs.get('creatinine'):.1f} mg/dL")
            concern_areas.append("Renal")

        liver = self.assess_liver_function(labs)
        if liver:
            narratives.append(liver)
            key_abnormalities.append(f"AST {labs.get('aspartate_aminotransferase'):.0f} U/L")
            concern_areas.append("Liver")

        coag = self.assess_coagulation(labs)
        if coag:
            narratives.append(coag)
            key_abnormalities.append(f"INR {labs.get('inr', 1.0):.1f}")
            concern_areas.append("Coagulation")

        infect = self.assess_infection(labs)
        if infect:
            narratives.append(infect)
            key_abnormalities.append(f"WBC {labs.get('white_blood_cell_count'):.1f} K/uL")
            concern_areas.append("Infection/Sepsis")

        gas = self.assess_gas_exchange(labs)
        if gas:
            narratives.append(gas)
            key_abnormalities.append(f"pO2 {labs.get('po2'):.0f} mmHg")
            concern_areas.append("Gas Exchange")

        summary = "\n\n".join(narratives)
        if not summary:
            summary = (
                "Laboratory values within reference ranges for all supplied tests. "
                "No acute abnormalities detected."
            )

        recommendation = (
            "Clinical assessment and serial lab monitoring recommended. "
            "Escalate care if patient develops new symptoms or vital sign changes."
        )

        return ClinicalNarrative(
            summary=summary,
            key_abnormalities=key_abnormalities,
            concern_areas=list(set(concern_areas)),
            recommendation=recommendation,
            caveats=caveats,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Example: critically ill patient
    panel = {
        "creatinine": 2.8,
        "blood_urea_nitrogen": 68,
        "aspartate_aminotransferase": 145,
        "alanine_aminotransferase": 120,
        "bilirubin": 2.3,
        "albumin": 2.5,
        "inr": 1.8,
        "white_blood_cell_count": 18.2,
        "procalcitonin": 2.1,
        "lactate": 3.2,
        "po2": 58,
        "pco2": 52,
        "ph": 7.24,
        "platelet_count": 85,
    }

    composer = NarrativeComposer()
    narrative = composer.compose(panel)

    print("═" * 70)
    print("CLINICAL LAB NARRATIVE")
    print("═" * 70)
    print("\n" + narrative.summary)
    print("\n" + "─" * 70)
    print("KEY ABNORMALITIES:")
    for abn in narrative.key_abnormalities:
        print(f"  • {abn}")

    print("\nCONCERN AREAS:")
    for area in narrative.concern_areas:
        print(f"  • {area}")

    print("\nRECOMMENDATION:")
    print(f"  {narrative.recommendation}")

    print("\nCAVEATS:")
    for caveat in narrative.caveats:
        print(f"  • {caveat}")
    print("═" * 70)
