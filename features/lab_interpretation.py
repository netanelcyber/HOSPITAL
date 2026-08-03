"""Differential generation from abnormal lab patterns.

**What this does and does not claim.** It produces a *differential* — a ranked
list of conditions worth considering given a pattern of abnormal results. It
does not produce a diagnosis, and the distinction is not pedantry: a diagnosis
requires history, examination and often imaging, none of which a lab panel
contains. Isolated hyperkalaemia is a haemolysed sample far more often than it
is Addison's disease, and no amount of text mining over the number 6.2 can tell
those apart.

**Where the clinical content comes from.** The pattern rules below are written
here, in code, where they can be reviewed, version-controlled and argued with.
They are *not* mined from prose. Wikipedia is used for one thing only: fetching
a plain-language explanation and a link for a condition that the curated rules
have already named. Inferring the medicine itself from an anonymously editable
encyclopedia would put an unaccountable source in the clinical path.

So the flow is:

    abnormal values -> curated pattern rules -> candidate conditions
                                                      |
                                      Wikipedia -> explanation text + link
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

from features.lab_features import LabFeatureExtractor

REFERENCE_RANGES = LabFeatureExtractor.REFERENCE_RANGES


@dataclass(frozen=True)
class LabFinding:
    """One analyte's deviation from its reference range."""

    analyte: str
    value: float
    low: float
    high: float
    direction: str  # "low" | "high" | "normal"
    severity: str   # "normal" | "mild" | "marked" | "critical"

    @property
    def is_abnormal(self) -> bool:
        return self.direction != "normal"


def classify(analyte: str, value: Optional[float]) -> Optional[LabFinding]:
    """Grade one value against its reference range."""
    if value is None:
        return None
    bounds = REFERENCE_RANGES.get(analyte)
    if bounds is None:
        return None

    low, high = bounds
    if value < low:
        direction = "low"
        ratio = value / low
        severity = "critical" if ratio < 0.5 else "marked" if ratio < 0.8 else "mild"
    elif value > high:
        direction = "high"
        ratio = value / high
        severity = "critical" if ratio > 2.0 else "marked" if ratio > 1.3 else "mild"
    else:
        direction, severity = "normal", "normal"

    return LabFinding(analyte, value, low, high, direction, severity)


@dataclass(frozen=True)
class DifferentialItem:
    """A condition to consider, with the evidence that raised it."""

    condition: str
    wikipedia_title: str
    rationale: str
    supporting: List[str]
    priority: str  # "urgent" | "important" | "routine"
    explanation: Optional[str] = None
    url: Optional[str] = None


@dataclass(frozen=True)
class PatternRule:
    """A curated rule mapping a lab pattern to a condition worth considering."""

    condition: str
    wikipedia_title: str
    rationale: str
    priority: str
    # Receives {analyte: LabFinding} for abnormal analytes only.
    matches: Callable[[Dict[str, LabFinding]], bool]
    supporting: Sequence[str] = field(default_factory=tuple)


def _abnormal(findings: Dict[str, LabFinding], analyte: str, direction: str) -> bool:
    finding = findings.get(analyte)
    return finding is not None and finding.direction == direction


def _at_least(findings: Dict[str, LabFinding], analyte: str, direction: str,
              severity: Sequence[str]) -> bool:
    finding = findings.get(analyte)
    return (
        finding is not None
        and finding.direction == direction
        and finding.severity in severity
    )


# Rules are ordered roughly by urgency. Each is deliberately narrow: a rule that
# fires on any single abnormality produces a differential so long it conveys
# nothing, which is the usual failure of automated interpretation.
PATTERN_RULES: tuple[PatternRule, ...] = (
    PatternRule(
        condition="Acute kidney injury",
        wikipedia_title="Acute kidney injury",
        rationale="Creatinine and urea nitrogen both raised — the classic paired "
                  "marker of falling glomerular filtration.",
        priority="urgent",
        supporting=("creatinine", "blood_urea_nitrogen"),
        matches=lambda f: _abnormal(f, "creatinine", "high")
                          and _abnormal(f, "blood_urea_nitrogen", "high"),
    ),
    PatternRule(
        condition="Prerenal azotaemia (volume depletion)",
        wikipedia_title="Prerenal kidney failure",
        rationale="Urea nitrogen raised disproportionately to creatinine, the "
                  "pattern seen when renal perfusion falls before parenchyma is "
                  "injured.",
        priority="important",
        supporting=("blood_urea_nitrogen", "creatinine"),
        matches=lambda f: _at_least(f, "blood_urea_nitrogen", "high", ("marked", "critical"))
                          and not _abnormal(f, "creatinine", "high"),
    ),
    PatternRule(
        condition="Sepsis / systemic infection",
        wikipedia_title="Sepsis",
        rationale="Leukocytosis with thrombocytopenia — consumption of platelets "
                  "alongside a leukocyte response suggests systemic infection "
                  "rather than a localized one.",
        priority="urgent",
        supporting=("white_blood_cell_count", "platelet_count"),
        matches=lambda f: _abnormal(f, "white_blood_cell_count", "high")
                          and _abnormal(f, "platelet_count", "low"),
    ),
    PatternRule(
        condition="Neutropenia / immunosuppression",
        wikipedia_title="Neutropenia",
        rationale="Leukocyte count markedly low. Infection may present without "
                  "the usual leukocytosis, so a normal count does not reassure.",
        priority="urgent",
        supporting=("white_blood_cell_count",),
        matches=lambda f: _at_least(f, "white_blood_cell_count", "low", ("marked", "critical")),
    ),
    PatternRule(
        condition="Disseminated intravascular coagulation",
        wikipedia_title="Disseminated intravascular coagulation",
        rationale="Thrombocytopenia with prolonged clotting times — simultaneous "
                  "consumption of platelets and coagulation factors.",
        priority="urgent",
        supporting=("platelet_count", "prothrombin_time", "partial_thromboplastin_time"),
        matches=lambda f: _abnormal(f, "platelet_count", "low")
                          and (_abnormal(f, "prothrombin_time", "high")
                               or _abnormal(f, "partial_thromboplastin_time", "high")),
    ),
    PatternRule(
        condition="Hyperkalaemia",
        wikipedia_title="Hyperkalemia",
        rationale="Potassium above range carries arrhythmia risk. Haemolysis of "
                  "the sample is the commonest cause of a spurious result and is "
                  "worth excluding before treating.",
        priority="urgent",
        supporting=("potassium",),
        matches=lambda f: _at_least(f, "potassium", "high", ("marked", "critical")),
    ),
    PatternRule(
        condition="Hypokalaemia",
        wikipedia_title="Hypokalemia",
        rationale="Potassium below range, also arrhythmogenic; commonly follows "
                  "diuretics or gastrointestinal losses.",
        priority="urgent",
        supporting=("potassium",),
        matches=lambda f: _at_least(f, "potassium", "low", ("marked", "critical")),
    ),
    PatternRule(
        condition="Hyponatraemia",
        wikipedia_title="Hyponatremia",
        rationale="Sodium below range. Rate of change matters more than the "
                  "absolute value, and correcting too fast carries its own risk.",
        priority="important",
        supporting=("sodium",),
        matches=lambda f: _abnormal(f, "sodium", "low"),
    ),
    PatternRule(
        condition="Hepatocellular injury",
        wikipedia_title="Elevated transaminases",
        rationale="Transaminases raised, indicating hepatocyte damage.",
        priority="important",
        supporting=("alanine_aminotransferase", "aspartate_aminotransferase"),
        matches=lambda f: _abnormal(f, "alanine_aminotransferase", "high")
                          or _abnormal(f, "aspartate_aminotransferase", "high"),
    ),
    PatternRule(
        condition="Cholestasis",
        wikipedia_title="Cholestasis",
        rationale="Alkaline phosphatase and bilirubin raised together, suggesting "
                  "obstructed bile flow rather than hepatocellular injury.",
        priority="important",
        supporting=("alkaline_phosphatase", "bilirubin"),
        matches=lambda f: _abnormal(f, "alkaline_phosphatase", "high")
                          and _abnormal(f, "bilirubin", "high"),
    ),
    PatternRule(
        condition="Anaemia",
        wikipedia_title="Anemia",
        rationale="Haemoglobin below range. Acute blood loss and chronic anaemia "
                  "look identical on a single draw; the trend distinguishes them.",
        priority="important",
        supporting=("hemoglobin", "hematocrit"),
        matches=lambda f: _abnormal(f, "hemoglobin", "low"),
    ),
    PatternRule(
        condition="Hyperglycaemia / diabetic emergency",
        wikipedia_title="Diabetic ketoacidosis",
        rationale="Glucose markedly raised. Ketoacidosis and hyperosmolar state "
                  "both require urgent recognition.",
        priority="urgent",
        supporting=("glucose",),
        matches=lambda f: _at_least(f, "glucose", "high", ("marked", "critical")),
    ),
    PatternRule(
        condition="Hypoglycaemia",
        wikipedia_title="Hypoglycemia",
        rationale="Glucose below range — an immediately reversible cause of "
                  "altered consciousness.",
        priority="urgent",
        supporting=("glucose",),
        matches=lambda f: _abnormal(f, "glucose", "low"),
    ),
    PatternRule(
        condition="Hypoalbuminaemia",
        wikipedia_title="Hypoalbuminemia",
        rationale="Albumin low, seen in malnutrition, liver disease, nephrotic "
                  "loss and as a negative acute-phase response.",
        priority="routine",
        supporting=("albumin",),
        matches=lambda f: _abnormal(f, "albumin", "low"),
    ),
)

PRIORITY_ORDER = {"urgent": 0, "important": 1, "routine": 2}


class LabInterpreter:
    """Turns a lab panel into a ranked differential, optionally annotated."""

    def __init__(self, wikipedia_client=None, enrich: bool = False):
        """
        Args:
            wikipedia_client: a `data.wikipedia.WikipediaClient`
            enrich: fetch explanation text for each condition. Off by default:
                it makes network calls, and the differential is complete
                without it — the encyclopedia adds readability, not medicine.
        """
        self.enrich = enrich
        self._client = wikipedia_client
        if enrich and wikipedia_client is None:
            from data.wikipedia import WikipediaClient

            self._client = WikipediaClient()

    def findings(self, labs: Dict[str, Optional[float]]) -> List[LabFinding]:
        """Grade every supplied value, keeping only the abnormal ones."""
        graded = (classify(analyte, value) for analyte, value in labs.items())
        abnormal = [f for f in graded if f is not None and f.is_abnormal]
        return sorted(
            abnormal,
            key=lambda f: {"critical": 0, "marked": 1, "mild": 2}[f.severity],
        )

    def differential(
        self, labs: Dict[str, Optional[float]], max_items: int = 6
    ) -> List[DifferentialItem]:
        """Conditions to consider, most urgent first."""
        by_analyte = {f.analyte: f for f in self.findings(labs)}
        if not by_analyte:
            return []

        matched: List[DifferentialItem] = []
        for rule in PATTERN_RULES:
            try:
                if not rule.matches(by_analyte):
                    continue
            except Exception as exc:  # a rule must never break the whole panel
                logger.warning("Rule %r raised %s", rule.condition, exc)
                continue

            matched.append(
                DifferentialItem(
                    condition=rule.condition,
                    wikipedia_title=rule.wikipedia_title,
                    rationale=rule.rationale,
                    supporting=[a for a in rule.supporting if a in by_analyte],
                    priority=rule.priority,
                )
            )

        matched.sort(key=lambda item: PRIORITY_ORDER[item.priority])
        matched = matched[:max_items]

        return [self._enrich(item) for item in matched] if self.enrich else matched

    def _enrich(self, item: DifferentialItem) -> DifferentialItem:
        """Attach a plain-language summary and link from Wikipedia.

        Failure is non-fatal by design: the differential came from the curated
        rules, so losing the encyclopedia text loses readability, not content.
        """
        title = item.wikipedia_title
        explanation, url = None, None

        try:
            resolved = self._client.resolve_title(title) or title
            summary = self._client.summary(resolved)
            if summary:
                # First two sentences: the lead's opening defines the condition,
                # and the rest drifts into epidemiology and history.
                parts = summary.replace("\n", " ").split(". ")
                explanation = ". ".join(parts[:2]).strip()
                if explanation and not explanation.endswith("."):
                    explanation += "."
            url = "https://en.wikipedia.org/wiki/" + resolved.replace(" ", "_")
        except Exception as exc:
            logger.warning("Wikipedia enrichment failed for %r: %s", title, exc)
            url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")

        return DifferentialItem(
            condition=item.condition,
            wikipedia_title=item.wikipedia_title,
            rationale=item.rationale,
            supporting=item.supporting,
            priority=item.priority,
            explanation=explanation,
            url=url,
        )

    def report(self, labs: Dict[str, Optional[float]]) -> str:
        """A readable summary, with the framing stated up front."""
        findings = self.findings(labs)
        if not findings:
            return "All supplied values are within their reference ranges."

        lines = ["Abnormal results:"]
        for f in findings:
            lines.append(
                f"  {f.analyte}: {f.value:g} ({f.direction}, {f.severity}; "
                f"reference {f.low}–{f.high})"
            )

        differential = self.differential(labs)
        if differential:
            lines.append("\nConsider (differential, not a diagnosis):")
            for item in differential:
                lines.append(f"  [{item.priority}] {item.condition}")
                lines.append(f"      {item.rationale}")
                if item.explanation:
                    lines.append(f"      {item.explanation}")

        lines.append(
            "\nThese are patterns worth considering, not conclusions. Laboratory "
            "values do not establish a diagnosis without history and examination."
        )
        return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    panel = {
        "creatinine": 3.4,
        "blood_urea_nitrogen": 62,
        "potassium": 5.9,
        "platelet_count": 78,
        "white_blood_cell_count": 21.5,
        "hemoglobin": 8.7,
        "sodium": 128,
        "glucose": 244,
    }

    print(LabInterpreter(enrich=False).report(panel))
