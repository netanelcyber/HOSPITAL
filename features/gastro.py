"""Gastroenterology and hepatology scoring from laboratory values.

Hepatology is unusually well suited to a lab-only system: several of the scores
that drive real clinical decisions are computed entirely from the panel. MELD
allocates liver transplants in the United States from four analytes. FIB-4 and
APRI are recommended first-line non-invasive fibrosis tests precisely because
they need nothing but age, transaminases and platelets.

That changes what this module should be. The deterioration model had to *learn*
its function from data. These scores are already published, externally
validated on far larger cohorts than anything available here, and — critically —
auditable: a clinician can recompute MELD by hand and check it. Fitting a model
to approximate them would replace a traceable formula with an opaque one and
lose accuracy in the process.

So the scores are implemented as the published formulae, with their real
clamping rules, and the learned component is confined to where a formula does
not already exist.

**Boundaries.** Every score here has published limits that matter more than the
arithmetic:

- MELD is validated as a 3-month mortality predictor in chronic liver disease.
  It is not a diagnostic test and misleads in acute liver failure.
- FIB-4 and APRI have indeterminate zones between their cutoffs — roughly a
  third of patients land there, and the honest output is "inconclusive, needs
  elastography or biopsy", not a forced call.
- Lipase above three times the upper limit is one of three Atlanta criteria for
  acute pancreatitis, not a diagnosis on its own. The degree of elevation does
  not track severity.

These limits are encoded, not just documented: scores return an explicit
interpretation band including the indeterminate one.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


# Upper limits of normal used by the published formulae. AST_ULN appears
# directly in APRI, so it is a parameter of the score rather than a lab detail.
AST_ULN = 40.0   # U/L
ALT_ULN = 56.0   # U/L
ALP_ULN = 147.0  # U/L
LIPASE_ULN = 160.0   # U/L
AMYLASE_ULN = 100.0  # U/L


# Analytes this module needs beyond the general panel.
GASTRO_ANALYTES: Dict[str, tuple] = {
    "lipase": (13, 60),                    # U/L
    "amylase": (30, 110),                  # U/L
    "gamma_glutamyl_transferase": (9, 48), # U/L
    "inr": (0.8, 1.2),                     # ratio
    "ammonia": (15, 45),                   # µmol/L
    "lactate": (0.5, 2.2),                 # mmol/L
    "ferritin": (24, 336),                 # ng/mL
    "transferrin_saturation": (20, 50),    # %
    "c_reactive_protein": (0, 5),          # mg/L
    "fecal_calprotectin": (0, 50),         # µg/g
    "triglycerides": (0, 150),             # mg/dL
    "calcium": (8.5, 10.5),                # mg/dL
}


@dataclass(frozen=True)
class ScoreResult:
    """One computed score with its interpretation and provenance."""

    name: str
    value: Optional[float]
    band: str                    # interpretation, incl. "indeterminate"
    interpretation: str
    inputs_used: Dict[str, float] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    reference: str = ""
    caveat: str = ""

    @property
    def computable(self) -> bool:
        return self.value is not None

    def __repr__(self) -> str:
        if not self.computable:
            return f"ScoreResult({self.name}, missing={self.missing})"
        return f"ScoreResult({self.name}={self.value:.2f}, {self.band})"


def _require(labs: Dict[str, Optional[float]], needed: Sequence[str]):
    """Split requested analytes into present values and a missing list."""
    present, missing = {}, []
    for name in needed:
        value = labs.get(name)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            missing.append(name)
        else:
            present[name] = float(value)
    return present, missing


def _unavailable(name: str, missing: List[str], reference: str = "") -> ScoreResult:
    return ScoreResult(
        name=name,
        value=None,
        band="not_computable",
        interpretation=f"Requires {', '.join(missing)}.",
        missing=missing,
        reference=reference,
    )


# --------------------------------------------------------------------------
# Liver: severity and prognosis
# --------------------------------------------------------------------------

def meld_na(
    labs: Dict[str, Optional[float]], on_dialysis: bool = False
) -> ScoreResult:
    """MELD-Na — 3-month mortality in chronic liver disease.

    The clamping rules are part of the score, not defensive programming: values
    below 1.0 are set to 1.0 so the logarithms cannot go negative, creatinine is
    capped at 4.0, and dialysis in the past week sets creatinine to 4.0
    regardless of the measured value, because dialysis masks the very
    dysfunction the term is measuring.

    Sodium is clamped to 125-137 before the correction. UNOS caps the final
    score at 40.
    """
    present, missing = _require(labs, ["bilirubin", "inr", "creatinine"])
    if missing:
        return _unavailable("MELD-Na", missing, "Kim WR et al. N Engl J Med 2008")

    bilirubin = max(present["bilirubin"], 1.0)
    inr = max(present["inr"], 1.0)
    creatinine = max(present["creatinine"], 1.0)
    if on_dialysis:
        creatinine = 4.0
    creatinine = min(creatinine, 4.0)

    meld = (
        3.78 * math.log(bilirubin)
        + 11.2 * math.log(inr)
        + 9.57 * math.log(creatinine)
        + 6.43
    )
    meld = round(meld)

    sodium = labs.get("sodium")
    used = {"bilirubin": bilirubin, "inr": inr, "creatinine": creatinine}
    if sodium is not None and not math.isnan(float(sodium)):
        sodium = min(max(float(sodium), 125.0), 137.0)
        used["sodium"] = sodium
        # The sodium correction only applies above MELD 11.
        if meld > 11:
            meld = meld + 1.32 * (137 - sodium) - 0.033 * meld * (137 - sodium)
        name = "MELD-Na"
    else:
        name = "MELD"

    score = min(max(round(meld), 6), 40)

    if score >= 30:
        band, interp = "very_high", "≈52% 3-month mortality untreated; transplant priority."
    elif score >= 20:
        band, interp = "high", "≈20% 3-month mortality; hepatology referral."
    elif score >= 15:
        band, interp = "moderate", "≈6% 3-month mortality; transplant benefit begins here."
    elif score >= 10:
        band, interp = "mild", "≈2% 3-month mortality."
    else:
        band, interp = "low", "≈2% 3-month mortality; low short-term risk."

    return ScoreResult(
        name=name,
        value=float(score),
        band=band,
        interpretation=interp,
        inputs_used=used,
        reference="Kim WR et al. N Engl J Med 2008;359:1018 (MELD-Na)",
        caveat="Validated for chronic liver disease. Not a diagnostic test, and "
               "misleading in acute liver failure.",
    )


def fib4(labs: Dict[str, Optional[float]], age: Optional[float]) -> ScoreResult:
    """FIB-4 — non-invasive advanced fibrosis estimate.

    Recommended first-line in NAFLD pathways. Two cutoffs and a wide
    indeterminate zone between them, which is reported rather than collapsed:
    forcing a call there is precisely the misuse the published guidance warns
    against.
    """
    present, missing = _require(labs, ["aspartate_aminotransferase",
                                       "alanine_aminotransferase", "platelet_count"])
    if age is None:
        missing.append("age")
    if missing:
        return _unavailable("FIB-4", missing, "Sterling RK et al. Hepatology 2006")

    ast = present["aspartate_aminotransferase"]
    alt = present["alanine_aminotransferase"]
    platelets = present["platelet_count"]

    if platelets <= 0 or alt <= 0:
        return _unavailable("FIB-4", ["valid platelet_count and ALT"],
                            "Sterling RK et al. Hepatology 2006")

    value = (float(age) * ast) / (platelets * math.sqrt(alt))

    # Age-adjusted lower cutoff: 1.30 under 65, 2.0 at 65 and above, because the
    # original cutoff produces excessive false positives in older patients.
    lower = 2.0 if age >= 65 else 1.30

    if value < lower:
        band = "low"
        interp = f"Advanced fibrosis unlikely (<{lower}); high negative predictive value."
    elif value > 2.67:
        band = "high"
        interp = "Advanced fibrosis likely (>2.67); refer for elastography or biopsy."
    else:
        band = "indeterminate"
        interp = (f"Between {lower} and 2.67 — indeterminate. About a third of "
                  "patients land here; elastography is the next step, not a guess.")

    return ScoreResult(
        name="FIB-4",
        value=round(value, 2),
        band=band,
        interpretation=interp,
        inputs_used={"age": float(age), "ast": ast, "alt": alt, "platelets": platelets},
        reference="Sterling RK et al. Hepatology 2006;43:1317",
        caveat="Unreliable under 35 or over 65 without the adjusted cutoff, and "
               "in acute hepatitis where transaminases are transiently extreme.",
    )


def apri(labs: Dict[str, Optional[float]]) -> ScoreResult:
    """APRI — AST-to-platelet ratio index for fibrosis and cirrhosis."""
    present, missing = _require(labs, ["aspartate_aminotransferase", "platelet_count"])
    if missing:
        return _unavailable("APRI", missing, "Wai CT et al. Hepatology 2003")

    platelets = present["platelet_count"]
    if platelets <= 0:
        return _unavailable("APRI", ["valid platelet_count"], "Wai CT et al. Hepatology 2003")

    value = (present["aspartate_aminotransferase"] / AST_ULN * 100.0) / platelets

    if value < 0.5:
        band, interp = "low", "Significant fibrosis unlikely (<0.5)."
    elif value > 1.5:
        band, interp = "high", "Significant fibrosis likely (>1.5); cirrhosis suggested above 2.0."
    else:
        band, interp = "indeterminate", "Between 0.5 and 1.5 — inconclusive on its own."

    return ScoreResult(
        name="APRI",
        value=round(value, 2),
        band=band,
        interpretation=interp,
        inputs_used={"ast": present["aspartate_aminotransferase"],
                     "platelets": platelets, "ast_uln": AST_ULN},
        reference="Wai CT et al. Hepatology 2003;38:518",
        caveat="Developed in hepatitis C; performs less well in other aetiologies.",
    )


def maddrey_discriminant_function(labs: Dict[str, Optional[float]],
                                  control_pt: float = 12.0) -> ScoreResult:
    """Maddrey DF — severity of alcoholic hepatitis; ≥32 defines severe disease."""
    present, missing = _require(labs, ["prothrombin_time", "bilirubin"])
    if missing:
        return _unavailable("Maddrey DF", missing, "Maddrey WC et al. Gastroenterology 1978")

    value = 4.6 * (present["prothrombin_time"] - control_pt) + present["bilirubin"]

    if value >= 32:
        band = "severe"
        interp = ("Severe alcoholic hepatitis (≥32); ≈35% 1-month mortality "
                  "untreated. Corticosteroid benefit is assessed at this threshold.")
    else:
        band, interp = "non_severe", "Below the 32 threshold for severe disease."

    return ScoreResult(
        name="Maddrey DF",
        value=round(value, 1),
        band=band,
        interpretation=interp,
        inputs_used={"prothrombin_time": present["prothrombin_time"],
                     "bilirubin": present["bilirubin"], "control_pt": control_pt},
        reference="Maddrey WC et al. Gastroenterology 1978;75:193",
        caveat="Assumes a clinical diagnosis of alcoholic hepatitis; the score "
               "grades severity and does not establish the diagnosis.",
    )


# --------------------------------------------------------------------------
# Liver: injury pattern
# --------------------------------------------------------------------------

def r_factor(labs: Dict[str, Optional[float]]) -> ScoreResult:
    """R-factor — hepatocellular vs cholestatic pattern of liver injury.

    The single most useful discriminator for narrowing a raised-LFT
    differential, and it changes the entire workup: hepatocellular points to
    viral and toxic causes, cholestatic to imaging for obstruction.
    """
    present, missing = _require(labs, ["alanine_aminotransferase", "alkaline_phosphatase"])
    if missing:
        return _unavailable("R-factor", missing, "Danan G, Benichou C. J Clin Epidemiol 1993")

    alp = present["alkaline_phosphatase"]
    if alp <= 0:
        return _unavailable("R-factor", ["valid alkaline_phosphatase"], "")

    value = (present["alanine_aminotransferase"] / ALT_ULN) / (alp / ALP_ULN)

    if value >= 5:
        band = "hepatocellular"
        interp = ("Hepatocellular injury (R≥5). Consider viral hepatitis, "
                  "drug-induced injury, autoimmune, ischaemic hepatitis.")
    elif value <= 2:
        band = "cholestatic"
        interp = ("Cholestatic injury (R≤2). Imaging for biliary obstruction; "
                  "consider PBC, PSC, drug-induced cholestasis.")
    else:
        band = "mixed"
        interp = "Mixed pattern (2<R<5); drug-induced injury commonly presents this way."

    return ScoreResult(
        name="R-factor",
        value=round(value, 2),
        band=band,
        interpretation=interp,
        inputs_used={"alt": present["alanine_aminotransferase"], "alp": alp},
        reference="Danan G, Benichou C. J Clin Epidemiol 1993;46:1323 (RUCAM)",
    )


def de_ritis_ratio(labs: Dict[str, Optional[float]]) -> ScoreResult:
    """AST/ALT ratio. Above 2 with raised GGT suggests alcoholic liver disease."""
    present, missing = _require(labs, ["aspartate_aminotransferase",
                                       "alanine_aminotransferase"])
    if missing:
        return _unavailable("AST/ALT ratio", missing, "De Ritis F et al. 1957")

    alt = present["alanine_aminotransferase"]
    if alt <= 0:
        return _unavailable("AST/ALT ratio", ["valid ALT"], "")

    value = present["aspartate_aminotransferase"] / alt
    ggt = labs.get("gamma_glutamyl_transferase")

    if value > 2.0:
        band = "alcoholic_pattern"
        interp = "AST/ALT >2 suggests alcoholic liver disease"
        interp += (", supported by the raised GGT." if ggt and ggt > 48
                   else "; GGT would support this.")
    elif value > 1.0:
        band = "elevated"
        interp = "AST/ALT >1 — seen in cirrhosis of any aetiology and in NASH with fibrosis."
    else:
        band = "normal"
        interp = "AST/ALT <1 — the usual pattern in viral hepatitis and NAFLD without fibrosis."

    return ScoreResult(
        name="AST/ALT ratio",
        value=round(value, 2),
        band=band,
        interpretation=interp,
        inputs_used={"ast": present["aspartate_aminotransferase"], "alt": alt},
        reference="De Ritis F et al. Clin Chim Acta 1957;2:70",
        caveat="AST also rises from muscle; rhabdomyolysis mimics this pattern.",
    )


# --------------------------------------------------------------------------
# Pancreas and gut
# --------------------------------------------------------------------------

def pancreatitis_enzymes(labs: Dict[str, Optional[float]]) -> ScoreResult:
    """Lipase and amylase against the Atlanta biochemical criterion.

    Lipase ≥3× ULN is *one of three* Atlanta criteria — the others being
    characteristic pain and imaging — and two of the three establish the
    diagnosis. Degree of elevation does not grade severity, a point worth
    stating because the number invites that reading.
    """
    present, missing = _require(labs, ["lipase"])
    if missing:
        present, missing = _require(labs, ["amylase"])
        if missing:
            return _unavailable("Pancreatic enzymes", ["lipase or amylase"],
                                "Banks PA et al. Gut 2013 (Revised Atlanta)")

    if "lipase" in present:
        value, uln, enzyme = present["lipase"], LIPASE_ULN, "lipase"
    else:
        value, uln, enzyme = present["amylase"], AMYLASE_ULN, "amylase"

    multiple = value / uln

    if multiple >= 3.0:
        band = "atlanta_positive"
        interp = (f"{enzyme.capitalize()} ≥3× ULN ({multiple:.1f}×) — meets the "
                  "Atlanta biochemical criterion. Diagnosis needs two of three: "
                  "this, characteristic pain, or imaging.")
    elif multiple >= 1.0:
        band = "raised"
        interp = (f"{enzyme.capitalize()} raised ({multiple:.1f}× ULN) but below 3×. "
                  "Seen in renal impairment, bowel ischaemia and perforation.")
    else:
        band = "normal"
        interp = (f"{enzyme.capitalize()} normal. Does not exclude pancreatitis "
                  "presenting late or in chronic disease with lost parenchyma.")

    return ScoreResult(
        name=f"Pancreatic {enzyme}",
        value=round(multiple, 2),
        band=band,
        interpretation=interp,
        inputs_used={enzyme: value, "uln": uln},
        reference="Banks PA et al. Gut 2013;62:102 (Revised Atlanta)",
        caveat="Degree of elevation does not track severity. Lipase is more "
               "specific than amylase and stays raised longer.",
    )


def bisap_lab_component(labs: Dict[str, Optional[float]],
                        age: Optional[float] = None) -> ScoreResult:
    """The lab-derivable part of BISAP for pancreatitis severity.

    BISAP has five components; only urea and age come from data available here.
    Impaired mental status, SIRS and pleural effusion require examination and
    imaging. The partial score is reported as partial — presenting it as BISAP
    would understate severity in exactly the sick patients it exists to find.
    """
    present, missing = _require(labs, ["blood_urea_nitrogen"])
    if missing:
        return _unavailable("BISAP (partial)", missing, "Wu BU et al. Gut 2008")

    points, components = 0, []
    if present["blood_urea_nitrogen"] > 25:
        points += 1
        components.append("urea nitrogen >25 mg/dL")
    if age is not None and age > 60:
        points += 1
        components.append("age >60")

    return ScoreResult(
        name="BISAP (partial)",
        value=float(points),
        band="partial",
        interpretation=(
            f"{points} of 2 lab/demographic components present"
            + (f": {', '.join(components)}. " if components else ". ")
            + "Three further components — impaired mental status, SIRS, pleural "
              "effusion — need examination and imaging. A full BISAP ≥3 marks "
              "high mortality risk."
        ),
        inputs_used={"blood_urea_nitrogen": present["blood_urea_nitrogen"]},
        reference="Wu BU et al. Gut 2008;57:1698",
        caveat="Incomplete by construction. Do not read as a full BISAP.",
    )


def glasgow_blatchford_lab_component(
    labs: Dict[str, Optional[float]], sex: str = "unknown"
) -> ScoreResult:
    """Lab-derivable part of the Glasgow-Blatchford score for upper GI bleeding.

    Urea and haemoglobin carry most of the score's weight; the remainder needs
    blood pressure, pulse, melaena, syncope and comorbidity. A full GBS of 0
    identifies patients safe for outpatient management — a decision this partial
    score must never be used to make.
    """
    present, missing = _require(labs, ["blood_urea_nitrogen", "hemoglobin"])
    if missing:
        return _unavailable("Glasgow-Blatchford (partial)", missing,
                            "Blatchford O et al. Lancet 2000")

    # GBS uses blood urea in mmol/L; BUN in mg/dL converts by 0.357.
    urea = present["blood_urea_nitrogen"] * 0.357
    hemoglobin = present["hemoglobin"]

    points = 0
    for threshold, score in ((25.0, 6), (10.0, 4), (8.0, 3), (6.5, 2)):
        if urea >= threshold:
            points += score
            break

    female = sex.lower().startswith("f")
    if hemoglobin < 10.0:
        points += 6
    elif not female and hemoglobin < 12.0:
        points += 3 if hemoglobin < 12.0 else 0
    elif female and hemoglobin < 12.0:
        points += 1

    return ScoreResult(
        name="Glasgow-Blatchford (partial)",
        value=float(points),
        band="partial",
        interpretation=(
            f"{points} points from urea ({urea:.1f} mmol/L) and haemoglobin "
            f"({hemoglobin:.1f} g/dL). Blood pressure, pulse, melaena, syncope "
            "and comorbidity are not included."
        ),
        inputs_used={"urea_mmol": round(urea, 2), "hemoglobin": hemoglobin},
        reference="Blatchford O et al. Lancet 2000;356:1318",
        caveat="A full GBS of 0 supports outpatient management. This partial "
               "score cannot support that decision.",
    )


# --------------------------------------------------------------------------
# Panel
# --------------------------------------------------------------------------

class GastroPanel:
    """Computes every applicable GI score for one patient."""

    def __init__(self, age: Optional[float] = None, sex: str = "unknown",
                 on_dialysis: bool = False):
        self.age = age
        self.sex = sex
        self.on_dialysis = on_dialysis

    def compute(self, labs: Dict[str, Optional[float]]) -> List[ScoreResult]:
        """Every score, including those that could not be computed.

        Non-computable scores are returned rather than dropped: "MELD needs an
        INR you did not send" is actionable, and a silently absent score reads
        as a normal one.
        """
        return [
            meld_na(labs, self.on_dialysis),
            fib4(labs, self.age),
            apri(labs),
            r_factor(labs),
            de_ritis_ratio(labs),
            maddrey_discriminant_function(labs),
            pancreatitis_enzymes(labs),
            bisap_lab_component(labs, self.age),
            glasgow_blatchford_lab_component(labs, self.sex),
        ]

    def computable(self, labs: Dict[str, Optional[float]]) -> List[ScoreResult]:
        return [s for s in self.compute(labs) if s.computable]

    def report(self, labs: Dict[str, Optional[float]]) -> str:
        results = self.compute(labs)
        computed = [r for r in results if r.computable]
        blocked = [r for r in results if not r.computable]

        lines = ["Gastroenterology / hepatology panel", "=" * 40]
        for result in computed:
            lines.append(f"\n{result.name}: {result.value}  [{result.band}]")
            lines.append(f"  {result.interpretation}")
            if result.caveat:
                lines.append(f"  Caveat: {result.caveat}")
            lines.append(f"  {result.reference}")

        if blocked:
            lines.append("\nNot computable:")
            for result in blocked:
                lines.append(f"  {result.name} — needs {', '.join(result.missing)}")

        lines.append(
            "\nThese are published, externally validated scores. They grade "
            "severity and narrow a differential; none of them establishes a "
            "diagnosis without clinical assessment."
        )
        return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Decompensated alcoholic cirrhosis.
    panel = {
        "bilirubin": 6.8, "inr": 1.9, "creatinine": 1.6, "sodium": 129,
        "aspartate_aminotransferase": 180, "alanine_aminotransferase": 72,
        "alkaline_phosphatase": 210, "platelet_count": 88,
        "albumin": 2.4, "prothrombin_time": 19.5,
        "gamma_glutamyl_transferase": 340, "blood_urea_nitrogen": 32,
        "hemoglobin": 9.1,
    }
    print(GastroPanel(age=54, sex="male").report(panel))
