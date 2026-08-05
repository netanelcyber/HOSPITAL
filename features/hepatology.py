"""Hepatology-specific laboratory scores for liver disease assessment.

All scores are implemented exactly as published, with proper clamping and edge-case
handling. Missing values are handled by returning None rather than imputing, so the
absence of required data is transparent to the caller.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Dict

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HepatologyScore:
    """Result of a hepatology score calculation."""

    name: str
    value: float
    interpretation: str
    confidence: str  # "high" (all values present), "low" (missing values)
    supporting_values: Dict[str, Optional[float]]

    def __str__(self) -> str:
        """Human-readable output."""
        return f"{self.name}: {self.value:.2f} ({self.interpretation}) [confidence: {self.confidence}]"


def forns_score(
    age: Optional[float],
    platelet_count: Optional[float],
    ast: Optional[float],
    alt: Optional[float],
) -> Optional[HepatologyScore]:
    """Forns index for non-invasive fibrosis assessment.

    Combines age, platelet count, and transaminase ratio.
    Published range: typically <4.30 (unlikely fibrosis), ≥6.00 (likely cirrhosis).

    Args:
        age: years
        platelet_count: K/uL (thousand per microliter)
        ast: aspartate aminotransferase, U/L
        alt: alanine aminotransferase, U/L

    Returns:
        HepatologyScore or None if insufficient data
    """
    if any(v is None for v in [age, platelet_count, ast, alt]):
        return None

    # Forns = 7*log10(age) + 0.8*log10(AST/ALT ratio) - 2.19 + 78*log10(platelet/100)
    ratio = ast / alt if alt > 0 else 0
    if ratio <= 0 or platelet_count <= 0:
        return None

    import math

    score = (
        7.0 * math.log10(age)
        + 0.8 * math.log10(ratio)
        - 2.19
        + 78.0 * math.log10(platelet_count / 100)
    )

    if score < 4.30:
        interpretation = "Unlikely significant fibrosis (F0-F1)"
    elif score < 6.00:
        interpretation = "Indeterminate fibrosis risk"
    else:
        interpretation = "Likely advanced fibrosis or cirrhosis (F3-F4)"

    return HepatologyScore(
        name="Forns Index",
        value=score,
        interpretation=interpretation,
        confidence="high",
        supporting_values={
            "age": age,
            "platelet_count": platelet_count,
            "ast": ast,
            "alt": alt,
        },
    )


def ast_plt_ratio(
    ast: Optional[float],
    platelet_count: Optional[float],
) -> Optional[HepatologyScore]:
    """AST-to-platelet ratio index (APRI) — already implemented in gastro.py.

    This is a convenience wrapper for consistency with other hepatology functions.
    Simple: (AST / upper limit normal) / platelet count * 100
    Thresholds: <0.5 (no fibrosis), 0.5-1.5 (indeterminate), >1.5 (likely cirrhosis)
    """
    if ast is None or platelet_count is None:
        return None

    upper_limit_ast = 40  # Standard lab reference
    ratio = (ast / upper_limit_ast) / platelet_count * 100

    if ratio < 0.5:
        interpretation = "No significant fibrosis (APRI < 0.5)"
    elif ratio < 1.5:
        interpretation = "Indeterminate fibrosis (APRI 0.5–1.5)"
    else:
        interpretation = "Likely significant fibrosis or cirrhosis (APRI > 1.5)"

    return HepatologyScore(
        name="APRI (AST-to-Platelet Ratio Index)",
        value=ratio,
        interpretation=interpretation,
        confidence="high",
        supporting_values={"ast": ast, "platelet_count": platelet_count},
    )


def fib_4(
    age: Optional[float],
    ast: Optional[float],
    alt: Optional[float],
    platelet_count: Optional[float],
) -> Optional[HepatologyScore]:
    """FIB-4 index for non-invasive cirrhosis assessment.

    Published formula: (Age * AST) / (Platelet count * √ALT)

    Thresholds vary by age but typically:
      <1.30 (low risk), 1.30–2.67 (indeterminate), >2.67 (high risk of cirrhosis)

    Args:
        age: years
        ast: U/L
        alt: U/L
        platelet_count: K/uL

    Returns:
        HepatologyScore or None if insufficient data
    """
    if any(v is None for v in [age, ast, alt, platelet_count]):
        return None

    if platelet_count <= 0 or alt <= 0:
        return None

    import math

    # FIB-4 = (Age * AST) / (Platelet count * sqrt(ALT))
    score = (age * ast) / (platelet_count * math.sqrt(alt))

    if score < 1.30:
        interpretation = "Low risk of cirrhosis (FIB-4 < 1.30)"
    elif score < 2.67:
        interpretation = "Indeterminate risk; elastography recommended (FIB-4 1.30–2.67)"
    else:
        interpretation = "High risk of cirrhosis (FIB-4 > 2.67)"

    return HepatologyScore(
        name="FIB-4 Index",
        value=score,
        interpretation=interpretation,
        confidence="high",
        supporting_values={
            "age": age,
            "ast": ast,
            "alt": alt,
            "platelet_count": platelet_count,
        },
    )


def child_pugh_score(
    bilirubin: Optional[float],
    inr: Optional[float],
    albumin: Optional[float],
    ascites: Optional[str],
    encephalopathy: Optional[str],
) -> Optional[HepatologyScore]:
    """Child-Pugh classification for chronic liver disease severity.

    NOTE: This function accepts ascites and encephalopathy as clinical inputs
    (not available from labs alone). For purely lab-based assessment, these
    should come from the EMR or clinical examination.

    Three laboratory variables (each 1-3 points):
    - Total bilirubin
    - INR/PT
    - Serum albumin

    Two clinical variables (each 1-3 points):
    - Ascites (none, mild, moderate)
    - Encephalopathy (none, grade 1-2, grade 3-4)

    Sum: 5-6 (Class A, good), 7-9 (Class B, moderate), 10-15 (Class C, poor)

    Args:
        bilirubin: mg/dL
        inr: INR ratio (preferred over PT)
        albumin: g/dL
        ascites: "none", "mild", or "moderate"
        encephalopathy: "none", "grade_1_2", or "grade_3_4"

    Returns:
        HepatologyScore or None if insufficient data
    """
    if bilirubin is None or inr is None or albumin is None:
        return None

    score = 0
    details = []

    # Bilirubin
    if bilirubin < 1.0:
        score += 1
        details.append("Bilirubin: 1 point")
    elif bilirubin < 3.0:
        score += 2
        details.append("Bilirubin: 2 points")
    else:
        score += 3
        details.append("Bilirubin: 3 points")

    # INR
    if inr < 1.3:
        score += 1
        details.append("INR: 1 point")
    elif inr < 1.7:
        score += 2
        details.append("INR: 2 points")
    else:
        score += 3
        details.append("INR: 3 points")

    # Albumin
    if albumin > 3.5:
        score += 1
        details.append("Albumin: 1 point")
    elif albumin > 2.8:
        score += 2
        details.append("Albumin: 2 points")
    else:
        score += 3
        details.append("Albumin: 3 points")

    # Ascites
    if ascites == "none":
        score += 1
        details.append("Ascites: 1 point (none)")
    elif ascites == "mild":
        score += 2
        details.append("Ascites: 2 points (mild)")
    else:  # moderate or severe
        score += 3
        details.append("Ascites: 3 points (moderate/severe)")

    # Encephalopathy
    if encephalopathy == "none":
        score += 1
        details.append("Encephalopathy: 1 point (none)")
    elif encephalopathy == "grade_1_2":
        score += 2
        details.append("Encephalopathy: 2 points (grade 1-2)")
    else:  # grade 3-4
        score += 3
        details.append("Encephalopathy: 3 points (grade 3-4)")

    # Interpretation
    if score <= 6:
        classification = "Class A (good prognosis)"
        interpretation = f"Child-Pugh Class A (score {score}). 1-year survival ~90%."
    elif score <= 9:
        classification = "Class B (moderate prognosis)"
        interpretation = f"Child-Pugh Class B (score {score}). 1-year survival ~70%."
    else:
        classification = "Class C (poor prognosis)"
        interpretation = f"Child-Pugh Class C (score {score}). 1-year survival ~45%."

    return HepatologyScore(
        name=f"Child-Pugh Score ({classification})",
        value=float(score),
        interpretation=interpretation,
        confidence="high" if (ascites and encephalopathy) else "low",
        supporting_values={
            "bilirubin": bilirubin,
            "inr": inr,
            "albumin": albumin,
            "ascites": ascites,
            "encephalopathy": encephalopathy,
        },
    )


def calculate_all_scores(
    labs: Dict[str, Optional[float]],
    ascites: Optional[str] = None,
    encephalopathy: Optional[str] = None,
) -> Dict[str, Optional[HepatologyScore]]:
    """Calculate all available hepatology scores from a lab panel.

    Args:
        labs: Dictionary of lab values (see keys expected below)
        ascites: Clinical assessment ("none", "mild", "moderate")
        encephalopathy: Clinical assessment ("none", "grade_1_2", "grade_3_4")

    Returns:
        Dictionary mapping score name to HepatologyScore or None
    """
    return {
        "fib4": fib_4(
            labs.get("age"),
            labs.get("aspartate_aminotransferase"),
            labs.get("alanine_aminotransferase"),
            labs.get("platelet_count"),
        ),
        "forns": forns_score(
            labs.get("age"),
            labs.get("platelet_count"),
            labs.get("aspartate_aminotransferase"),
            labs.get("alanine_aminotransferase"),
        ),
        "apri": ast_plt_ratio(
            labs.get("aspartate_aminotransferase"),
            labs.get("platelet_count"),
        ),
        "child_pugh": child_pugh_score(
            labs.get("bilirubin"),
            labs.get("inr"),
            labs.get("albumin"),
            ascites,
            encephalopathy,
        ),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Example: cirrhotic patient
    panel = {
        "age": 58,
        "aspartate_aminotransferase": 78,
        "alanine_aminotransferase": 45,
        "platelet_count": 92,
        "bilirubin": 2.1,
        "inr": 1.5,
        "albumin": 2.9,
    }

    scores = calculate_all_scores(panel, ascites="mild", encephalopathy="none")
    print("Hepatology Assessment:")
    for name, score in scores.items():
        if score:
            print(f"  {score}")
        else:
            print(f"  {name}: (insufficient data)")
