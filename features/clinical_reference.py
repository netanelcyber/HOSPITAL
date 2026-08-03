"""Clinical reference integration: LOINC harmonization and UpToDate linking.

**On UpToDate.** UpToDate is proprietary, licensed content. Its terms of service
prohibit automated retrieval, redistribution and derivative use of the article
text, so this module never ingests it and never trains on it. What it does
provide is a *link-out* helper against UpToDate's official Web Services API,
which hospitals license separately: given a concept, it returns a deep link a
clinician can open, so a risk score can be presented next to the relevant
topic. Content stays on Wolters Kluwer's side of the line; only the URL crosses.
Calls require the hospital's own credentials and are disabled by default.

**What actually helps the model** is LOINC. Every source in `public_datasets`
names its analytes differently — MIMIC uses numeric itemids, eICU uses free
text, AmsterdamUMCdb uses Dutch. LOINC is the international standard code for
laboratory observations, it is free to use, and mapping every source onto it is
what makes a pooled multi-site cohort coherent rather than merely concatenated.
Unit harmonization matters just as much: creatinine in µmol/L (European sites)
against mg/dL (US sites) differs by a factor of 88.4, and pooling them
unconverted silently destroys the feature.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LOINC
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LoincAnalyte:
    """A canonical analyte, its LOINC code and its reference unit."""

    name: str
    loinc_code: str
    long_name: str
    canonical_unit: str


# LOINC codes for the panel this system predicts from, all serum/plasma.
LOINC_PANEL: Tuple[LoincAnalyte, ...] = (
    LoincAnalyte("glucose", "2345-7", "Glucose [Mass/volume] in Serum or Plasma", "mg/dL"),
    LoincAnalyte("hemoglobin", "718-7", "Hemoglobin [Mass/volume] in Blood", "g/dL"),
    LoincAnalyte("potassium", "2823-3", "Potassium [Moles/volume] in Serum or Plasma", "mmol/L"),
    LoincAnalyte("sodium", "2951-2", "Sodium [Moles/volume] in Serum or Plasma", "mmol/L"),
    LoincAnalyte("creatinine", "2160-0", "Creatinine [Mass/volume] in Serum or Plasma", "mg/dL"),
    LoincAnalyte("blood_urea_nitrogen", "3094-0", "Urea nitrogen [Mass/volume] in Serum or Plasma", "mg/dL"),
    LoincAnalyte("alanine_aminotransferase", "1742-6", "Alanine aminotransferase [Enzymatic activity/volume]", "U/L"),
    LoincAnalyte("aspartate_aminotransferase", "1920-8", "Aspartate aminotransferase [Enzymatic activity/volume]", "U/L"),
    LoincAnalyte("alkaline_phosphatase", "6768-6", "Alkaline phosphatase [Enzymatic activity/volume]", "U/L"),
    LoincAnalyte("bilirubin", "1975-2", "Bilirubin.total [Mass/volume] in Serum or Plasma", "mg/dL"),
    LoincAnalyte("albumin", "1751-7", "Albumin [Mass/volume] in Serum or Plasma", "g/dL"),
    LoincAnalyte("prothrombin_time", "5902-2", "Prothrombin time (PT)", "s"),
    LoincAnalyte("partial_thromboplastin_time", "14979-9", "aPTT in Platelet poor plasma", "s"),
    LoincAnalyte("platelet_count", "777-3", "Platelets [#/volume] in Blood", "10*3/uL"),
    LoincAnalyte("white_blood_cell_count", "6690-2", "Leukocytes [#/volume] in Blood", "10*3/uL"),
    LoincAnalyte("red_blood_cell_count", "789-8", "Erythrocytes [#/volume] in Blood", "10*6/uL"),
    LoincAnalyte("hematocrit", "4544-3", "Hematocrit [Volume Fraction] of Blood", "%"),
)

LOINC_BY_NAME: Dict[str, LoincAnalyte] = {a.name: a for a in LOINC_PANEL}
LOINC_BY_CODE: Dict[str, LoincAnalyte] = {a.loinc_code: a for a in LOINC_PANEL}


# Multiplicative factors converting a source unit to the canonical unit.
# Molar/mass conversions use each analyte's molecular weight, so they are
# per-analyte rather than generic.
UNIT_CONVERSIONS: Dict[str, Dict[str, float]] = {
    "glucose": {"mg/dl": 1.0, "mmol/l": 18.016, "g/l": 100.0},
    "creatinine": {"mg/dl": 1.0, "umol/l": 1.0 / 88.4, "µmol/l": 1.0 / 88.4, "mmol/l": 1000.0 / 88.4},
    # European sites report urea, not urea nitrogen; BUN = urea / 2.14.
    "blood_urea_nitrogen": {"mg/dl": 1.0, "mmol/l": 2.8, "g/l": 100.0},
    "hemoglobin": {"g/dl": 1.0, "g/l": 0.1, "mmol/l": 1.611},
    "bilirubin": {"mg/dl": 1.0, "umol/l": 1.0 / 17.1, "µmol/l": 1.0 / 17.1},
    "albumin": {"g/dl": 1.0, "g/l": 0.1},
    "potassium": {"mmol/l": 1.0, "meq/l": 1.0},
    "sodium": {"mmol/l": 1.0, "meq/l": 1.0},
    "platelet_count": {"10*3/ul": 1.0, "k/ul": 1.0, "10^9/l": 1.0, "10*9/l": 1.0, "/ul": 1e-3},
    "white_blood_cell_count": {"10*3/ul": 1.0, "k/ul": 1.0, "10^9/l": 1.0, "10*9/l": 1.0, "/ul": 1e-3},
    "red_blood_cell_count": {"10*6/ul": 1.0, "m/ul": 1.0, "10^12/l": 1.0, "10*12/l": 1.0},
    "hematocrit": {"%": 1.0, "l/l": 100.0, "fraction": 100.0},
    "alanine_aminotransferase": {"u/l": 1.0, "iu/l": 1.0, "ukat/l": 0.06},
    "aspartate_aminotransferase": {"u/l": 1.0, "iu/l": 1.0, "ukat/l": 0.06},
    "alkaline_phosphatase": {"u/l": 1.0, "iu/l": 1.0, "ukat/l": 0.06},
    "prothrombin_time": {"s": 1.0, "sec": 1.0, "seconds": 1.0},
    "partial_thromboplastin_time": {"s": 1.0, "sec": 1.0, "seconds": 1.0},
}


# Physiologically possible ranges, in canonical units. Values outside these are
# transcription or unit errors, not extreme patients: a potassium of 400 is a
# data-entry artifact, and leaving it in lets one row dominate the scaler.
PLAUSIBLE_RANGES: Dict[str, Tuple[float, float]] = {
    "glucose": (10.0, 2000.0),
    "hemoglobin": (1.0, 25.0),
    "potassium": (1.0, 10.0),
    "sodium": (90.0, 190.0),
    "creatinine": (0.05, 30.0),
    "blood_urea_nitrogen": (1.0, 300.0),
    "alanine_aminotransferase": (1.0, 20000.0),
    "aspartate_aminotransferase": (1.0, 20000.0),
    "alkaline_phosphatase": (5.0, 5000.0),
    "bilirubin": (0.05, 60.0),
    "albumin": (0.5, 7.0),
    "prothrombin_time": (5.0, 200.0),
    "partial_thromboplastin_time": (10.0, 300.0),
    "platelet_count": (1.0, 3000.0),
    "white_blood_cell_count": (0.05, 500.0),
    "red_blood_cell_count": (0.5, 10.0),
    "hematocrit": (5.0, 75.0),
}


class LoincHarmonizer:
    """Maps source lab values onto LOINC-coded, unit-normalized analytes."""

    def __init__(self, drop_implausible: bool = True):
        self.drop_implausible = drop_implausible
        self._dropped_counts: Dict[str, int] = {}

    @staticmethod
    def normalize_unit(unit: Optional[str]) -> str:
        if unit is None or (isinstance(unit, float) and np.isnan(unit)):
            return ""
        return str(unit).strip().lower().replace(" ", "")

    def convert(
        self, analyte: str, values: pd.Series, unit: Optional[str]
    ) -> pd.Series:
        """Convert a series of values from `unit` into the canonical unit."""
        table = UNIT_CONVERSIONS.get(analyte)
        if table is None:
            return values

        key = self.normalize_unit(unit)
        if not key:
            # No unit recorded: assume the source already uses the canonical
            # unit rather than silently scaling by a guess.
            return values

        factor = table.get(key)
        if factor is None:
            logger.warning(
                "Unknown unit %r for %s; leaving values unconverted", unit, analyte
            )
            return values

        return values * factor

    def clip_implausible(self, analyte: str, values: pd.Series) -> pd.Series:
        """Blank out values outside the physiologically possible range."""
        bounds = PLAUSIBLE_RANGES.get(analyte)
        if bounds is None or not self.drop_implausible:
            return values

        low, high = bounds
        mask = values.notna() & ((values < low) | (values > high))
        count = int(mask.sum())
        if count:
            self._dropped_counts[analyte] = self._dropped_counts.get(analyte, 0) + count
            logger.info(
                "%s: blanked %d values outside [%g, %g]", analyte, count, low, high
            )
        return values.mask(mask)

    def harmonize_frame(
        self, df: pd.DataFrame, units: Optional[Dict[str, str]] = None
    ) -> pd.DataFrame:
        """Harmonize every ``lab_<analyte>`` column of a cohort frame.

        Args:
            df: cohort with lab_* columns
            units: per-analyte source unit, e.g. {"creatinine": "umol/L"}
        """
        units = units or {}
        result = df.copy()

        for column in [c for c in result.columns if c.startswith("lab_")]:
            analyte = self._analyte_of(column)
            if analyte is None:
                continue
            values = pd.to_numeric(result[column], errors="coerce")
            values = self.convert(analyte, values, units.get(analyte))
            result[column] = self.clip_implausible(analyte, values)

        return result

    @staticmethod
    def _analyte_of(column: str) -> Optional[str]:
        """Recover the analyte from a lab column, including stat suffixes."""
        stem = column[len("lab_"):]
        if stem in LOINC_BY_NAME:
            return stem
        # Columns produced by _pivot_labs look like lab_<analyte>_<stat>.
        for suffix in ("_first", "_last", "_min", "_max", "_mean"):
            if stem.endswith(suffix):
                candidate = stem[: -len(suffix)]
                if candidate in LOINC_BY_NAME:
                    return candidate
        return None

    def coverage_report(self, df: pd.DataFrame) -> pd.DataFrame:
        """Per-analyte presence, LOINC code and blanked-value count."""
        rows = []
        for analyte, loinc in LOINC_BY_NAME.items():
            column = f"lab_{analyte}"
            present = column in df.columns
            rows.append(
                {
                    "analyte": analyte,
                    "loinc_code": loinc.loinc_code,
                    "unit": loinc.canonical_unit,
                    "present": present,
                    "non_null": int(df[column].notna().sum()) if present else 0,
                    "blanked_implausible": self._dropped_counts.get(analyte, 0),
                }
            )
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# UpToDate link-out
# ---------------------------------------------------------------------------

class UpToDateLinker:
    """Builds deep links into UpToDate for concepts the model flagged.

    This is deliberately a linker and not a client. UpToDate content is
    licensed, and its terms forbid automated retrieval and derivative use, so
    nothing here fetches article text, caches it, or feeds it to a model. The
    output is a URL for a clinician to click.

    `search_url` needs no credentials and works for any institution whose users
    are already authenticated to UpToDate. `resolve_topic` uses the official
    Web Services API and stays disabled unless the hospital supplies its own
    licensed credentials.
    """

    SEARCH_ENDPOINT = "https://www.uptodate.com/contents/search"

    # Concept names from features.clinical_nlp mapped to UpToDate search terms.
    CONCEPT_SEARCH_TERMS: Dict[str, str] = {
        "sepsis": "sepsis in adults evaluation and management",
        "septic_shock": "septic shock in adults vasopressors",
        "respiratory_failure": "acute respiratory failure in adults",
        "renal_failure": "acute kidney injury in adults",
        "hepatic_failure": "acute liver failure in adults",
        "dic": "disseminated intravascular coagulation",
        "hypotension": "shock in adults evaluation",
        "altered_mental_status": "acute encephalopathy delirium in adults",
        "arrhythmia": "arrhythmia evaluation in adults",
        "hypoxia": "hypoxemia evaluation in adults",
        "hemorrhage": "approach to acute gastrointestinal bleeding in adults",
        "myocardial_infarction": "acute myocardial infarction management",
        "stroke": "acute ischemic stroke initial evaluation",
        "pulmonary_embolism": "acute pulmonary embolism treatment",
        "pneumonia": "community acquired pneumonia in adults",
        "infection": "fever in the hospitalized adult",
        "multi_organ_failure": "multiple organ dysfunction syndrome",
        "cardiac_arrest": "advanced cardiac life support in adults",
        "heart_failure": "acute decompensated heart failure",
        "ckd": "chronic kidney disease management",
        "diabetes": "diabetic ketoacidosis and hyperosmolar state",
        "copd": "copd exacerbation management",
        "malignancy": "oncologic emergencies",
        "immunosuppression": "fever in the neutropenic adult",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        enabled: bool = False,
    ):
        """
        Args:
            api_key: licensed UpToDate Web Services key. Read from
                UPTODATE_API_KEY when omitted.
            api_base: institution's Web Services base URL.
            enabled: must be set explicitly before any API call is attempted.
        """
        self.api_key = api_key or os.environ.get("UPTODATE_API_KEY")
        self.api_base = api_base or os.environ.get("UPTODATE_API_BASE")
        self.enabled = enabled and bool(self.api_key and self.api_base)

        if enabled and not self.enabled:
            logger.warning(
                "UpToDate API requested but UPTODATE_API_KEY/UPTODATE_API_BASE "
                "are not set; falling back to unauthenticated search links."
            )

    def search_url(self, concept: str) -> str:
        """A search deep link for a concept. No credentials, no content."""
        term = self.CONCEPT_SEARCH_TERMS.get(
            concept, concept.replace("_", " ")
        )
        return f"{self.SEARCH_ENDPOINT}?search={urllib.parse.quote(term)}"

    def links_for_mentions(self, concepts: Iterable[str]) -> Dict[str, str]:
        """Map each flagged concept to its reference link."""
        return {concept: self.search_url(concept) for concept in dict.fromkeys(concepts)}

    def resolve_topic(self, concept: str) -> Optional[Dict[str, str]]:
        """Resolve a concept to a topic id/title via the official API.

        Returns None unless the hospital's licensed credentials are configured.
        Only identifiers and titles are returned — never article body text.
        """
        if not self.enabled:
            return None

        import json
        import urllib.request

        term = self.CONCEPT_SEARCH_TERMS.get(concept, concept.replace("_", " "))
        url = (
            f"{self.api_base.rstrip('/')}/search"
            f"?search={urllib.parse.quote(term)}&limit=1"
        )
        request = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self.api_key}"}
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read())
        except Exception as exc:
            logger.warning("UpToDate lookup failed for %s: %s", concept, exc)
            return None

        results = payload.get("data", {}).get("searchResults") or payload.get("results") or []
        if not results:
            return None

        top = results[0]
        return {
            "concept": concept,
            "topic_id": str(top.get("id", "")),
            "title": str(top.get("title", "")),
            "url": str(top.get("url", self.search_url(concept))),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    frame = pd.DataFrame(
        {
            "patient_id": ["A", "B", "C"],
            # Third value is an implausible transcription error.
            "lab_creatinine": [88.4, 176.8, 99999.0],
            "lab_potassium": [4.1, 5.6, 3.2],
        }
    )

    harmonizer = LoincHarmonizer()
    # European site reporting creatinine in µmol/L.
    harmonized = harmonizer.harmonize_frame(frame, units={"creatinine": "umol/L"})
    print(harmonized)
    print()
    print(harmonizer.coverage_report(harmonized).head(6).to_string(index=False))

    linker = UpToDateLinker()
    print("\nReference links:")
    for concept, url in linker.links_for_mentions(["sepsis", "renal_failure"]).items():
        print(f"  {concept}: {url}")
