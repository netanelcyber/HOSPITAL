"""Adapters for open-source clinical datasets (internal medicine / ED admissions).

Supported sources
-----------------
============================  =========  ==============  ====================
Source                        Stays      Setting         Region
============================  =========  ==============  ====================
MIMIC-IV (hosp)               ~546,000   Ward/internal   Boston, US
MIMIC-IV-ED                   ~425,000   Emergency dept  Boston, US
eICU-CRD                      ~200,000   ICU/step-down   208 US hospitals
MIMIC-III                      ~58,000   ICU             Boston, US
HiRID                          ~33,000   ICU             Bern, Switzerland
AmsterdamUMCdb                 ~23,000   ICU             Amsterdam, NL
SICdb                          ~27,000   ICU             Salzburg, Austria
============================  =========  ==============  ====================

All of these are credentialed-access datasets (PhysioNet/Amsterdam DUA plus
CITI human-subjects training). This module does NOT download them. It reads
local CSV/CSV.GZ/Parquet extracts that the user has already obtained legally,
and normalizes them into the internal schema used by the rest of the pipeline.

Pooling several sources multiplies cohort size but also multiplies confounding:
assay methods, units and case mix differ per site. `MultiSourceCohortBuilder`
tags every row with its origin so that validation can be run leave-one-site-out
rather than on a shuffled pool, which is the only way to see whether a model
generalizes off the site it was trained on.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# LOINC / itemid -> canonical feature name used by LabFeatureExtractor.
# Mapping is intentionally explicit: silent fuzzy matching on lab names is a
# common source of label leakage and unit mix-ups in clinical ML.
MIMIC_LABITEM_MAP: Dict[int, str] = {
    50931: "glucose",
    51222: "hemoglobin",
    50971: "potassium",
    50983: "sodium",
    50912: "creatinine",
    51006: "blood_urea_nitrogen",
    50861: "alanine_aminotransferase",
    50878: "aspartate_aminotransferase",
    50863: "alkaline_phosphatase",
    50885: "bilirubin",
    50862: "albumin",
    51274: "prothrombin_time",
    51275: "partial_thromboplastin_time",
    51265: "platelet_count",
    51301: "white_blood_cell_count",
    51279: "red_blood_cell_count",
    51221: "hematocrit",
}

EICU_LABNAME_MAP: Dict[str, str] = {
    "glucose": "glucose",
    "Hgb": "hemoglobin",
    "potassium": "potassium",
    "sodium": "sodium",
    "creatinine": "creatinine",
    "BUN": "blood_urea_nitrogen",
    "ALT (SGPT)": "alanine_aminotransferase",
    "AST (SGOT)": "aspartate_aminotransferase",
    "alkaline phos.": "alkaline_phosphatase",
    "total bilirubin": "bilirubin",
    "albumin": "albumin",
    "PT": "prothrombin_time",
    "PTT": "partial_thromboplastin_time",
    "platelets x 1000": "platelet_count",
    "WBC x 1000": "white_blood_cell_count",
    "RBC": "red_blood_cell_count",
    "Hct": "hematocrit",
}


@dataclass
class DeteriorationLabelConfig:
    """Defines what counts as deterioration, and the prediction window.

    observation_hours: only labs drawn within this many hours of admission are
        used as features. Anything later risks leaking the outcome.
    prediction_horizon_hours: outcome is evaluated within this window, measured
        from the end of the observation window.
    """

    observation_hours: float = 24.0
    prediction_horizon_hours: float = 48.0
    include_icu_transfer: bool = True
    include_mortality: bool = True
    include_vasopressor: bool = False
    include_mechanical_ventilation: bool = False


class PublicDatasetAdapter(ABC):
    """Base adapter: local extract directory -> tidy lab/label frames."""

    def __init__(
        self,
        root: str | Path,
        label_config: Optional[DeteriorationLabelConfig] = None,
    ):
        self.root = Path(root)
        if not self.root.exists():
            raise FileNotFoundError(
                f"Dataset directory not found: {self.root}. "
                "These datasets are credentialed-access; download them from "
                "PhysioNet first and point this adapter at the extract."
            )
        self.label_config = label_config or DeteriorationLabelConfig()

    def _resolve(self, *candidates: str) -> Path:
        """Locate the first table that exists, trying .gz and .parquet variants."""
        for name in candidates:
            for suffix in ("", ".gz"):
                path = self.root / f"{name}{suffix}"
                if path.exists():
                    return path
            parquet = self.root / f"{Path(name).with_suffix('.parquet')}"
            if parquet.exists():
                return parquet
        raise FileNotFoundError(
            f"None of {candidates} found under {self.root} "
            "(tried .csv, .csv.gz and .parquet)"
        )

    def _read_table(self, *candidates: str, columns: Optional[List[str]] = None) -> pd.DataFrame:
        """Read a table whole. Use only for tables known to fit in memory."""
        path = self._resolve(*candidates)
        logger.info("Reading %s", path)
        if path.suffix == ".parquet":
            return pd.read_parquet(path, columns=columns)
        return pd.read_csv(path, low_memory=False, usecols=columns)

    def _read_filtered(
        self,
        *candidates: str,
        row_filter,
        columns: Optional[List[str]] = None,
        chunksize: int = 2_000_000,
    ) -> pd.DataFrame:
        """Stream a table too large for RAM, keeping only rows that survive.

        MIMIC-IV labevents is ~130M rows / ~13GB uncompressed; loading it whole
        needs more memory than most machines have. Filtering per chunk keeps
        peak usage proportional to the retained subset, not the file.
        """
        path = self._resolve(*candidates)
        logger.info("Streaming %s in chunks of %d rows", path, chunksize)

        if path.suffix == ".parquet":
            return row_filter(pd.read_parquet(path, columns=columns))

        kept: List[pd.DataFrame] = []
        rows_scanned = 0
        for chunk in pd.read_csv(
            path, low_memory=False, usecols=columns, chunksize=chunksize
        ):
            rows_scanned += len(chunk)
            filtered = row_filter(chunk)
            if len(filtered):
                kept.append(filtered)

        if not kept:
            raise ValueError(
                f"No rows survived filtering of {path} ({rows_scanned:,} scanned). "
                "Check that the itemid/labname mapping matches this extract."
            )

        result = pd.concat(kept, ignore_index=True)
        logger.info(
            "Kept %d of %d rows (%.2f%%) from %s",
            len(result),
            rows_scanned,
            100 * len(result) / rows_scanned,
            path.name,
        )
        return result

    @abstractmethod
    def build_cohort(self) -> pd.DataFrame:
        """Return one row per stay: lab_* columns, medical_report, deteriorated."""

    @staticmethod
    def _pivot_labs(
        labs: pd.DataFrame,
        stay_col: str,
        feature_col: str,
        value_col: str,
    ) -> pd.DataFrame:
        """Collapse long-format labs to one row per stay.

        Keeps first/last/min/max/mean per analyte. Trajectory matters more than
        any single draw — a creatinine of 1.4 means something different when it
        was 0.8 six hours earlier.
        """
        agg = labs.groupby([stay_col, feature_col])[value_col].agg(
            ["first", "last", "min", "max", "mean"]
        )
        agg = agg.unstack(feature_col)
        agg.columns = [f"lab_{analyte}_{stat}" for stat, analyte in agg.columns]

        # The plain lab_<analyte> column (last observed value) is what the
        # reference-range logic in LabFeatureExtractor expects.
        last = labs.sort_values(stay_col).groupby([stay_col, feature_col])[value_col].last()
        last = last.unstack(feature_col)
        last.columns = [f"lab_{analyte}" for analyte in last.columns]

        return last.join(agg).reset_index()


class MimicIVAdapter(PublicDatasetAdapter):
    """MIMIC-IV hosp module — general/internal medicine hospital admissions."""

    def build_cohort(self) -> pd.DataFrame:
        admissions = self._read_table("admissions.csv", "hosp/admissions.csv")

        admissions["admittime"] = pd.to_datetime(admissions["admittime"])
        admissions["dischtime"] = pd.to_datetime(admissions["dischtime"])
        if "deathtime" in admissions.columns:
            admissions["deathtime"] = pd.to_datetime(admissions["deathtime"])

        def keep_mapped_labs(chunk: pd.DataFrame) -> pd.DataFrame:
            chunk = chunk[chunk["itemid"].isin(MIMIC_LABITEM_MAP)].copy()
            chunk["valuenum"] = pd.to_numeric(chunk["valuenum"], errors="coerce")
            return chunk.dropna(subset=["valuenum", "hadm_id"])

        labevents = self._read_filtered(
            "labevents.csv",
            "hosp/labevents.csv",
            row_filter=keep_mapped_labs,
            columns=["hadm_id", "itemid", "charttime", "valuenum"],
        )
        labevents["analyte"] = labevents["itemid"].map(MIMIC_LABITEM_MAP)
        labevents["charttime"] = pd.to_datetime(labevents["charttime"])
        labevents["hadm_id"] = labevents["hadm_id"].astype("int64")

        labevents = labevents.merge(
            admissions[["hadm_id", "admittime"]], on="hadm_id", how="inner"
        )
        hours_since_admit = (
            labevents["charttime"] - labevents["admittime"]
        ).dt.total_seconds() / 3600.0
        labevents = labevents[
            (hours_since_admit >= 0)
            & (hours_since_admit <= self.label_config.observation_hours)
        ]

        features = self._pivot_labs(labevents, "hadm_id", "analyte", "valuenum")
        cohort = features.merge(admissions, on="hadm_id", how="inner")
        cohort["deteriorated"] = self._label(cohort)
        cohort["patient_id"] = cohort["hadm_id"].astype(str)
        cohort["medical_report"] = self._synthesize_report(cohort)

        keep = ["patient_id", "medical_report", "deteriorated"]
        keep += [c for c in cohort.columns if c.startswith("lab_")]
        result = cohort[keep]
        logger.info(
            "MIMIC-IV cohort: %d stays, %.1f%% deteriorated",
            len(result),
            100 * result["deteriorated"].mean(),
        )
        return result

    def _label(self, cohort: pd.DataFrame) -> pd.Series:
        cfg = self.label_config
        window_end = cohort["admittime"] + pd.Timedelta(
            hours=cfg.observation_hours + cfg.prediction_horizon_hours
        )
        label = pd.Series(False, index=cohort.index)

        if cfg.include_mortality:
            died = cohort.get("deathtime")
            if died is not None:
                label |= died.notna() & (died <= window_end)
            # hospital_expire_flag covers deaths without a recorded deathtime.
            if "hospital_expire_flag" in cohort.columns:
                label |= cohort["hospital_expire_flag"].fillna(0).astype(int).astype(bool)

        if cfg.include_icu_transfer:
            try:
                icustays = self._read_table("icustays.csv", "icu/icustays.csv")
                icustays["intime"] = pd.to_datetime(icustays["intime"])
                first_icu = icustays.groupby("hadm_id")["intime"].min()
                icu_time = cohort["hadm_id"].map(first_icu)
                # Only transfers after the observation window are predictable;
                # a patient already in ICU at hour 0 is not a deterioration event.
                obs_end = cohort["admittime"] + pd.Timedelta(hours=cfg.observation_hours)
                label |= icu_time.notna() & (icu_time > obs_end) & (icu_time <= window_end)
            except FileNotFoundError:
                logger.warning("icustays not found; ICU transfer excluded from label")

        return label.astype(int)

    @staticmethod
    def _synthesize_report(cohort: pd.DataFrame) -> pd.Series:
        """Build an admission summary from structured fields.

        MIMIC-IV's free-text notes live in a separate credentialed module
        (mimic-iv-note). When it is absent we fall back to the structured
        admission context, which is what the auxiliary channel needs anyway.
        """
        parts = []
        for col, prefix in [
            ("admission_type", "Admission type"),
            ("admission_location", "Admitted from"),
            ("insurance", "Insurance"),
            ("race", "Race"),
        ]:
            if col in cohort.columns:
                parts.append(f"{prefix}: " + cohort[col].fillna("unknown").astype(str))
        if not parts:
            return pd.Series("", index=cohort.index)
        report = parts[0]
        for part in parts[1:]:
            report = report + ". " + part
        return report + "."


class MimicIVEDAdapter(PublicDatasetAdapter):
    """MIMIC-IV-ED — emergency department stays (קבלה למלר\"ד)."""

    def build_cohort(self) -> pd.DataFrame:
        edstays = self._read_table("edstays.csv", "ed/edstays.csv")
        triage = self._read_table("triage.csv", "ed/triage.csv")

        edstays["intime"] = pd.to_datetime(edstays["intime"])
        edstays["outtime"] = pd.to_datetime(edstays["outtime"])

        cohort = edstays.merge(triage, on="stay_id", how="left", suffixes=("", "_triage"))

        # MIMIC-IV-ED has no lab table of its own; labs come from the linked
        # hosp module via subject_id. Without it we can still build the cohort
        # from triage vitals, but the lab channel would be empty — and this
        # system predicts from labs.
        def keep_mapped_labs(chunk: pd.DataFrame) -> pd.DataFrame:
            chunk = chunk[chunk["itemid"].isin(MIMIC_LABITEM_MAP)].copy()
            chunk["valuenum"] = pd.to_numeric(chunk["valuenum"], errors="coerce")
            return chunk.dropna(subset=["valuenum", "subject_id"])

        try:
            labevents = self._read_filtered(
                "labevents.csv",
                "hosp/labevents.csv",
                "../hosp/labevents.csv",
                row_filter=keep_mapped_labs,
                columns=["subject_id", "itemid", "charttime", "valuenum"],
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                "MIMIC-IV-ED contains no labs. Place the MIMIC-IV hosp "
                "labevents table alongside the ED extract so ED stays can be "
                "linked to lab draws by subject_id."
            ) from exc

        labevents["analyte"] = labevents["itemid"].map(MIMIC_LABITEM_MAP)
        labevents["charttime"] = pd.to_datetime(labevents["charttime"])

        # Attach each lab draw to the ED stay whose window contains it.
        labevents = labevents.merge(
            cohort[["stay_id", "subject_id", "intime", "outtime"]],
            on="subject_id",
            how="inner",
        )
        obs_end = labevents["intime"] + pd.Timedelta(
            hours=self.label_config.observation_hours
        )
        labevents = labevents[
            (labevents["charttime"] >= labevents["intime"])
            & (labevents["charttime"] <= obs_end)
        ]

        features = self._pivot_labs(labevents, "stay_id", "analyte", "valuenum")
        cohort = features.merge(cohort, on="stay_id", how="inner")

        cohort["deteriorated"] = self._label(cohort)
        cohort["patient_id"] = cohort["stay_id"].astype(str)
        cohort["medical_report"] = self._triage_report(cohort)

        keep = ["patient_id", "medical_report", "deteriorated"]
        keep += [c for c in cohort.columns if c.startswith("lab_")]
        result = cohort[keep]
        logger.info(
            "MIMIC-IV-ED cohort: %d stays, %.1f%% deteriorated",
            len(result),
            100 * result["deteriorated"].mean(),
        )
        return result

    def _label(self, cohort: pd.DataFrame) -> pd.Series:
        """ED deterioration: admitted to hospital, or died in the ED.

        `disposition` is the ED outcome field; ADMITTED covers ward and ICU.
        """
        label = pd.Series(False, index=cohort.index)
        if "disposition" in cohort.columns:
            disposition = cohort["disposition"].fillna("").str.upper()
            label |= disposition.isin({"ADMITTED", "EXPIRED"})
        return label.astype(int)

    @staticmethod
    def _triage_report(cohort: pd.DataFrame) -> pd.Series:
        """Triage note + vitals as the auxiliary clinical channel."""
        report = pd.Series("", index=cohort.index)

        if "chiefcomplaint" in cohort.columns:
            report = report + "Chief complaint: " + cohort["chiefcomplaint"].fillna(
                "unspecified"
            ).astype(str) + ". "

        if "acuity" in cohort.columns:
            # ESI 1-2 is the emergent end of the scale.
            acuity = pd.to_numeric(cohort["acuity"], errors="coerce")
            report = report + "Triage acuity: " + acuity.fillna(0).astype(int).astype(str)
            report = report + acuity.le(2).map(
                {True: " (emergent, acute presentation). ", False: ". "}
            ).fillna(". ")

        vitals = {
            "temperature": "Temp",
            "heartrate": "HR",
            "resprate": "RR",
            "o2sat": "SpO2",
            "sbp": "SBP",
            "dbp": "DBP",
            "pain": "Pain",
        }
        for col, label in vitals.items():
            if col in cohort.columns:
                values = pd.to_numeric(cohort[col], errors="coerce")
                report = report + f"{label}: " + values.round(1).astype(str) + ". "

        return report


class EICUAdapter(PublicDatasetAdapter):
    """eICU Collaborative Research Database — multi-center US ICU/step-down."""

    def build_cohort(self) -> pd.DataFrame:
        patient = self._read_table("patient.csv")
        lab = self._read_table("lab.csv")

        lab = lab[lab["labname"].isin(EICU_LABNAME_MAP)].copy()
        lab["analyte"] = lab["labname"].map(EICU_LABNAME_MAP)
        lab["labresult"] = pd.to_numeric(lab["labresult"], errors="coerce")
        lab = lab.dropna(subset=["labresult"])

        # eICU stores offsets in minutes from unit admission.
        window_minutes = self.label_config.observation_hours * 60
        lab = lab[
            (lab["labresultoffset"] >= 0) & (lab["labresultoffset"] <= window_minutes)
        ]

        features = self._pivot_labs(lab, "patientunitstayid", "analyte", "labresult")
        cohort = features.merge(patient, on="patientunitstayid", how="inner")

        cohort["deteriorated"] = self._label(cohort)
        cohort["patient_id"] = cohort["patientunitstayid"].astype(str)
        cohort["medical_report"] = self._synthesize_report(cohort)

        keep = ["patient_id", "medical_report", "deteriorated"]
        keep += [c for c in cohort.columns if c.startswith("lab_")]
        result = cohort[keep]
        logger.info(
            "eICU cohort: %d stays, %.1f%% deteriorated",
            len(result),
            100 * result["deteriorated"].mean(),
        )
        return result

    def _label(self, cohort: pd.DataFrame) -> pd.Series:
        label = pd.Series(False, index=cohort.index)
        for col in ("unitdischargestatus", "hospitaldischargestatus"):
            if col in cohort.columns:
                label |= cohort[col].fillna("").str.strip().str.lower().eq("expired")
        return label.astype(int)

    @staticmethod
    def _synthesize_report(cohort: pd.DataFrame) -> pd.Series:
        report = pd.Series("", index=cohort.index)
        if "apacheadmissiondx" in cohort.columns:
            report = report + "Admission diagnosis: " + cohort[
                "apacheadmissiondx"
            ].fillna("unspecified").astype(str) + ". "
        if "unittype" in cohort.columns:
            report = report + "Unit: " + cohort["unittype"].fillna("unknown").astype(str) + ". "
        if "age" in cohort.columns:
            report = report + "Age: " + cohort["age"].fillna("unknown").astype(str) + ". "
        return report


class MimicIIIAdapter(PublicDatasetAdapter):
    """MIMIC-III — the older Boston ICU cohort. Table names are uppercase."""

    def build_cohort(self) -> pd.DataFrame:
        admissions = self._read_table("ADMISSIONS.csv", "admissions.csv")
        admissions.columns = [c.lower() for c in admissions.columns]

        admissions["admittime"] = pd.to_datetime(admissions["admittime"])
        if "deathtime" in admissions.columns:
            admissions["deathtime"] = pd.to_datetime(admissions["deathtime"])

        def keep_mapped_labs(chunk: pd.DataFrame) -> pd.DataFrame:
            chunk.columns = [c.lower() for c in chunk.columns]
            chunk = chunk[chunk["itemid"].isin(MIMIC_LABITEM_MAP)].copy()
            chunk["valuenum"] = pd.to_numeric(chunk["valuenum"], errors="coerce")
            return chunk.dropna(subset=["valuenum", "hadm_id"])

        labevents = self._read_filtered(
            "LABEVENTS.csv", "labevents.csv", row_filter=keep_mapped_labs
        )
        labevents["analyte"] = labevents["itemid"].map(MIMIC_LABITEM_MAP)
        labevents["charttime"] = pd.to_datetime(labevents["charttime"])
        labevents["hadm_id"] = labevents["hadm_id"].astype("int64")

        labevents = labevents.merge(
            admissions[["hadm_id", "admittime"]], on="hadm_id", how="inner"
        )
        hours = (labevents["charttime"] - labevents["admittime"]).dt.total_seconds() / 3600
        labevents = labevents[
            (hours >= 0) & (hours <= self.label_config.observation_hours)
        ]

        features = self._pivot_labs(labevents, "hadm_id", "analyte", "valuenum")
        cohort = features.merge(admissions, on="hadm_id", how="inner")

        label = pd.Series(False, index=cohort.index)
        if "hospital_expire_flag" in cohort.columns:
            label |= cohort["hospital_expire_flag"].fillna(0).astype(int).astype(bool)
        cohort["deteriorated"] = label.astype(int)

        cohort["patient_id"] = cohort["hadm_id"].astype(str)
        cohort["medical_report"] = MimicIVAdapter._synthesize_report(cohort)

        keep = ["patient_id", "medical_report", "deteriorated"]
        keep += [c for c in cohort.columns if c.startswith("lab_")]
        return cohort[keep]


class HiridAdapter(PublicDatasetAdapter):
    """HiRID — high-resolution Bern ICU data, ~33k admissions.

    Observations live in `observation_tables` keyed by numeric variableid; the
    mapping to analytes comes from the shipped variable reference.
    """

    HIRID_VARIABLE_MAP: Dict[int, str] = {
        24000585: "glucose",
        24000836: "hemoglobin",
        24000520: "potassium",
        24000519: "sodium",
        24000572: "creatinine",
        24000734: "blood_urea_nitrogen",
        24000566: "alanine_aminotransferase",
        24000567: "aspartate_aminotransferase",
        24000575: "bilirubin",
        24000605: "albumin",
        24000512: "platelet_count",
        24000538: "white_blood_cell_count",
        24000548: "hematocrit",
    }

    def build_cohort(self) -> pd.DataFrame:
        general = self._read_table("general_table.csv", "reference_data/general_table.csv")
        general["admissiontime"] = pd.to_datetime(general["admissiontime"])

        def keep_mapped(chunk: pd.DataFrame) -> pd.DataFrame:
            chunk = chunk[chunk["variableid"].isin(self.HIRID_VARIABLE_MAP)].copy()
            chunk["value"] = pd.to_numeric(chunk["value"], errors="coerce")
            return chunk.dropna(subset=["value"])

        obs = self._read_filtered(
            "observation_tables.csv",
            "observation_tables/observation_tables.csv",
            row_filter=keep_mapped,
        )
        obs["analyte"] = obs["variableid"].map(self.HIRID_VARIABLE_MAP)
        obs["datetime"] = pd.to_datetime(obs["datetime"])

        obs = obs.merge(general[["patientid", "admissiontime"]], on="patientid", how="inner")
        hours = (obs["datetime"] - obs["admissiontime"]).dt.total_seconds() / 3600
        obs = obs[(hours >= 0) & (hours <= self.label_config.observation_hours)]

        features = self._pivot_labs(obs, "patientid", "analyte", "value")
        cohort = features.merge(general, on="patientid", how="inner")

        # HiRID encodes outcome as discharge status; 'dead' marks in-unit death.
        label = pd.Series(False, index=cohort.index)
        if "discharge_status" in cohort.columns:
            label |= cohort["discharge_status"].fillna("").str.lower().eq("dead")
        cohort["deteriorated"] = label.astype(int)

        cohort["patient_id"] = cohort["patientid"].astype(str)
        cohort["medical_report"] = (
            "ICU admission, Bern. Age group: "
            + cohort.get("age", pd.Series("unknown", index=cohort.index)).astype(str)
            + ". Sex: "
            + cohort.get("sex", pd.Series("unknown", index=cohort.index)).astype(str)
            + "."
        )

        keep = ["patient_id", "medical_report", "deteriorated"]
        keep += [c for c in cohort.columns if c.startswith("lab_")]
        return cohort[keep]


class AmsterdamUMCdbAdapter(PublicDatasetAdapter):
    """AmsterdamUMCdb — ~23k ICU admissions, European case mix.

    Numeric labs sit in `numericitems`; offsets are milliseconds from admission.
    """

    ITEM_NAME_MAP: Dict[str, str] = {
        "Glucose": "glucose",
        "Hb": "hemoglobin",
        "Kalium": "potassium",
        "Natrium": "sodium",
        "Kreatinine": "creatinine",
        "Ureum": "blood_urea_nitrogen",
        "ALAT": "alanine_aminotransferase",
        "ASAT": "aspartate_aminotransferase",
        "Alk.Fosf.": "alkaline_phosphatase",
        "Bili Totaal": "bilirubin",
        "Albumine": "albumin",
        "Thrombo's": "platelet_count",
        "Leuco's": "white_blood_cell_count",
        "Ht": "hematocrit",
    }

    def build_cohort(self) -> pd.DataFrame:
        admissions = self._read_table("admissions.csv")

        def keep_mapped(chunk: pd.DataFrame) -> pd.DataFrame:
            chunk = chunk[chunk["item"].isin(self.ITEM_NAME_MAP)].copy()
            chunk["value"] = pd.to_numeric(chunk["value"], errors="coerce")
            return chunk.dropna(subset=["value"])

        numeric = self._read_filtered(
            "numericitems.csv",
            row_filter=keep_mapped,
            columns=["admissionid", "item", "value", "measuredat"],
        )
        numeric["analyte"] = numeric["item"].map(self.ITEM_NAME_MAP)

        window_ms = self.label_config.observation_hours * 3600 * 1000
        numeric = numeric[
            (numeric["measuredat"] >= 0) & (numeric["measuredat"] <= window_ms)
        ]

        features = self._pivot_labs(numeric, "admissionid", "analyte", "value")
        cohort = features.merge(admissions, on="admissionid", how="inner")

        # dateofdeath is populated only for patients known to have died.
        label = pd.Series(False, index=cohort.index)
        if "dateofdeath" in cohort.columns:
            label |= cohort["dateofdeath"].notna()
        if "destination" in cohort.columns:
            label |= cohort["destination"].fillna("").str.lower().str.contains("overleden")
        cohort["deteriorated"] = label.astype(int)

        cohort["patient_id"] = cohort["admissionid"].astype(str)
        cohort["medical_report"] = (
            "ICU admission, Amsterdam UMC. Specialty: "
            + cohort.get("specialty", pd.Series("unknown", index=cohort.index))
            .fillna("unknown")
            .astype(str)
            + ". Urgency: "
            + cohort.get("urgency", pd.Series("unknown", index=cohort.index))
            .astype(str)
            + "."
        )

        keep = ["patient_id", "medical_report", "deteriorated"]
        keep += [c for c in cohort.columns if c.startswith("lab_")]
        return cohort[keep]


class SICdbAdapter(PublicDatasetAdapter):
    """SICdb — Salzburg Intensive Care database, ~27k admissions."""

    def build_cohort(self) -> pd.DataFrame:
        cases = self._read_table("cases.csv")
        laboratory = self._read_table("laboratory.csv")

        reference = self._read_table("d_references.csv", "reference.csv")
        # SICdb names analytes only in the reference table; join to get labels.
        name_col = next(
            (c for c in ("ReferenceName", "referencename", "name") if c in reference.columns),
            None,
        )
        id_col = next(
            (c for c in ("ReferenceGlobalID", "referenceglobalid", "id") if c in reference.columns),
            None,
        )
        if name_col is None or id_col is None:
            raise ValueError(
                f"Could not locate name/id columns in SICdb reference table: "
                f"{list(reference.columns)}"
            )

        canonical = {
            "glucose": "glucose",
            "hemoglobin": "hemoglobin",
            "haemoglobin": "hemoglobin",
            "potassium": "potassium",
            "sodium": "sodium",
            "creatinine": "creatinine",
            "urea": "blood_urea_nitrogen",
            "alat": "alanine_aminotransferase",
            "asat": "aspartate_aminotransferase",
            "bilirubin": "bilirubin",
            "albumin": "albumin",
            "platelets": "platelet_count",
            "leukocytes": "white_blood_cell_count",
            "hematocrit": "hematocrit",
        }
        reference["analyte"] = (
            reference[name_col].fillna("").str.strip().str.lower().map(canonical)
        )
        mapping = reference.dropna(subset=["analyte"]).set_index(id_col)["analyte"]

        laboratory["analyte"] = laboratory["LaboratoryID"].map(mapping)
        laboratory = laboratory.dropna(subset=["analyte"])
        laboratory["LaboratoryValue"] = pd.to_numeric(
            laboratory["LaboratoryValue"], errors="coerce"
        )
        laboratory = laboratory.dropna(subset=["LaboratoryValue"])

        window_seconds = self.label_config.observation_hours * 3600
        laboratory = laboratory[
            (laboratory["Offset"] >= 0) & (laboratory["Offset"] <= window_seconds)
        ]

        features = self._pivot_labs(
            laboratory, "CaseID", "analyte", "LaboratoryValue"
        )
        cohort = features.merge(cases, on="CaseID", how="inner")

        label = pd.Series(False, index=cohort.index)
        if "OffsetOfDeath" in cohort.columns:
            label |= cohort["OffsetOfDeath"].notna()
        cohort["deteriorated"] = label.astype(int)

        cohort["patient_id"] = cohort["CaseID"].astype(str)
        cohort["medical_report"] = "ICU admission, Salzburg."

        keep = ["patient_id", "medical_report", "deteriorated"]
        keep += [c for c in cohort.columns if c.startswith("lab_")]
        return cohort[keep]


ADAPTERS = {
    "mimic-iv": MimicIVAdapter,
    "mimic-iv-ed": MimicIVEDAdapter,
    "mimic-iii": MimicIIIAdapter,
    "eicu": EICUAdapter,
    "hirid": HiridAdapter,
    "amsterdamumcdb": AmsterdamUMCdbAdapter,
    "sicdb": SICdbAdapter,
}


def load_public_dataset(
    source: str,
    root: str | Path,
    label_config: Optional[DeteriorationLabelConfig] = None,
) -> pd.DataFrame:
    """Build a training-ready cohort from a local open-source dataset extract.

    Args:
        source: one of the keys of ADAPTERS
        root: directory holding the extracted tables
        label_config: observation window and outcome definition

    Returns:
        DataFrame with patient_id, lab_* columns, medical_report, deteriorated
    """
    if source not in ADAPTERS:
        raise ValueError(
            f"Unknown source {source!r}. Available: {sorted(ADAPTERS)}"
        )
    return ADAPTERS[source](root, label_config).build_cohort()


class MultiSourceCohortBuilder:
    """Pools several datasets into one cohort, keeping site provenance.

    Patient IDs collide across sources (both MIMIC and eICU number their stays
    from small integers), so every ID is prefixed with its source. The `source`
    column it adds is what makes leave-one-site-out validation possible.
    """

    def __init__(self, label_config: Optional[DeteriorationLabelConfig] = None):
        self.label_config = label_config or DeteriorationLabelConfig()
        self._sources: Dict[str, Path] = {}

    def add(self, source: str, root: str | Path) -> "MultiSourceCohortBuilder":
        if source not in ADAPTERS:
            raise ValueError(f"Unknown source {source!r}. Available: {sorted(ADAPTERS)}")
        self._sources[source] = Path(root)
        return self

    def build(self, skip_missing: bool = True) -> pd.DataFrame:
        """Load and concatenate every registered source.

        Args:
            skip_missing: log and continue when a source directory is absent,
                rather than failing the whole build.
        """
        if not self._sources:
            raise ValueError("No sources registered; call add() first.")

        frames: List[pd.DataFrame] = []
        for source, root in self._sources.items():
            try:
                cohort = ADAPTERS[source](root, self.label_config).build_cohort()
            except (FileNotFoundError, ValueError) as exc:
                if not skip_missing:
                    raise
                logger.warning("Skipping %s: %s", source, exc)
                continue

            cohort = cohort.copy()
            cohort["source"] = source
            cohort["patient_id"] = source + ":" + cohort["patient_id"].astype(str)
            frames.append(cohort)
            logger.info("%s contributed %d stays", source, len(cohort))

        if not frames:
            raise ValueError("No source produced a cohort.")

        pooled = pd.concat(frames, ignore_index=True, sort=False)

        # An analyte missing from a whole site stays NaN rather than being
        # imputed here; the feature extractor decides how to fill it, and it
        # needs to see which values were never measured.
        logger.info(
            "Pooled cohort: %d stays across %d sources, %.1f%% deteriorated",
            len(pooled),
            len(frames),
            100 * pooled["deteriorated"].mean(),
        )
        return pooled

    @staticmethod
    def site_summary(pooled: pd.DataFrame) -> pd.DataFrame:
        """Per-site row counts, event rates and lab coverage.

        Wide swings in event rate between sites usually mean the outcome
        definitions are not actually comparable, which matters more than the
        pooled headline number.
        """
        lab_cols = [c for c in pooled.columns if c.startswith("lab_")]
        summary = pooled.groupby("source").agg(
            stays=("patient_id", "count"),
            event_rate=("deteriorated", "mean"),
        )
        summary["lab_coverage"] = (
            pooled.groupby("source")[lab_cols].apply(lambda g: g.notna().mean().mean())
        )
        return summary.sort_values("stays", ascending=False)
