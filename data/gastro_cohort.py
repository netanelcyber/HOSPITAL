"""GI phenotypes from ICD codes, for training and for validating the scores.

Two uses. First, labels: a GI diagnosis model needs a target, and discharge ICD
codes are the only diagnosis labels these datasets carry. Second, and more
immediately useful, validation: FIB-4 and APRI claim to detect fibrosis, so
computing them on patients coded as cirrhotic and on everyone else is a direct
external check that the implementation reproduces the published behaviour.

**What ICD labels are worth.** They are billing codes assigned at discharge,
not a gold-standard adjudication. They under-code mild disease, over-code
whatever justifies reimbursement, and describe the whole admission rather than
the state at the time of the labs. Cirrhosis coding is among the more reliable
because it drives so much else in the record; NAFLD coding is notoriously poor.
Treated as noisy labels they are useful; treated as truth they will flatter any
model trained on them.

Both ICD-9 and ICD-10 appear in MIMIC, often in the same admission, so both are
mapped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Phenotype:
    """A GI phenotype and the codes that define it."""

    name: str
    icd9_prefixes: tuple = ()
    icd10_prefixes: tuple = ()
    description: str = ""

    def matches(self, code: str, version: int) -> bool:
        code = code.strip().upper().replace(".", "")
        prefixes = self.icd10_prefixes if version == 10 else self.icd9_prefixes
        return any(code.startswith(p) for p in prefixes)


# Ordered most to least specific: a patient coded for both cirrhosis and
# oesophageal varices is primarily a cirrhosis patient.
PHENOTYPES: tuple[Phenotype, ...] = (
    Phenotype(
        "cirrhosis",
        icd9_prefixes=("5710", "5712", "5715", "5716"),
        icd10_prefixes=("K703", "K717", "K74"),
        description="Cirrhosis, alcoholic and non-alcoholic",
    ),
    Phenotype(
        "portal_hypertension",
        icd9_prefixes=("5723",),
        icd10_prefixes=("K766",),
        description="Portal hypertension",
    ),
    Phenotype(
        "hepatorenal_syndrome",
        icd9_prefixes=("5724",),
        icd10_prefixes=("K767",),
        description="Hepatorenal syndrome",
    ),
    Phenotype(
        "hepatic_failure",
        icd9_prefixes=("5702", "5728"),
        icd10_prefixes=("K72",),
        description="Hepatic failure, acute and chronic",
    ),
    Phenotype(
        "alcoholic_liver_disease",
        icd9_prefixes=("5711", "5713"),
        icd10_prefixes=("K700", "K701", "K702", "K709"),
        description="Alcoholic hepatitis and steatosis",
    ),
    Phenotype(
        "nafld_nash",
        icd9_prefixes=("5718",),
        icd10_prefixes=("K758", "K760"),
        description="NAFLD and NASH",
    ),
    Phenotype(
        "viral_hepatitis",
        icd9_prefixes=("070",),
        icd10_prefixes=("B15", "B16", "B17", "B18", "B19"),
        description="Viral hepatitis",
    ),
    Phenotype(
        "acute_pancreatitis",
        icd9_prefixes=("5770",),
        icd10_prefixes=("K850", "K851", "K852", "K853", "K858", "K859"),
        description="Acute pancreatitis",
    ),
    Phenotype(
        "chronic_pancreatitis",
        icd9_prefixes=("5771",),
        icd10_prefixes=("K860", "K861"),
        description="Chronic pancreatitis",
    ),
    Phenotype(
        "biliary_obstruction",
        icd9_prefixes=("5740", "5743", "5745", "5760", "5762"),
        icd10_prefixes=("K80", "K831"),
        description="Cholelithiasis with obstruction, biliary stricture",
    ),
    Phenotype(
        "cholangitis",
        icd9_prefixes=("5761",),
        icd10_prefixes=("K830",),
        description="Cholangitis",
    ),
    Phenotype(
        "gi_bleeding",
        icd9_prefixes=("5780", "5781", "5789", "5311", "5321", "4560", "4562"),
        icd10_prefixes=("K920", "K921", "K922", "I850", "K250", "K260"),
        description="GI haemorrhage including variceal bleeding",
    ),
    Phenotype(
        "inflammatory_bowel_disease",
        icd9_prefixes=("555", "556"),
        icd10_prefixes=("K50", "K51"),
        description="Crohn disease and ulcerative colitis",
    ),
    Phenotype(
        "bowel_obstruction",
        icd9_prefixes=("5600", "5601", "5603", "5608", "5609"),
        icd10_prefixes=("K56",),
        description="Intestinal obstruction",
    ),
    Phenotype(
        "gerd_esophagitis",
        icd9_prefixes=("53081", "5301"),
        icd10_prefixes=("K21",),
        description="Reflux disease and oesophagitis",
    ),
)


class GastroCohortBuilder:
    """Attaches GI phenotype labels to a cohort from ICD codes."""

    def __init__(self, data_root: str | Path):
        self.root = Path(data_root)

    def _diagnoses_path(self) -> Path:
        for candidate in (
            self.root / "hosp" / "diagnoses_icd.csv",
            self.root / "hosp" / "diagnoses_icd.csv.gz",
            self.root / "DIAGNOSES_ICD.csv",
            self.root / "DIAGNOSES_ICD.csv.gz",
        ):
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"No diagnoses_icd table under {self.root}")

    def load_labels(self) -> pd.DataFrame:
        """One row per admission, one boolean column per phenotype."""
        path = self._diagnoses_path()
        logger.info("Reading %s", path)

        diagnoses = pd.read_csv(path, dtype=str)
        diagnoses.columns = [c.lower() for c in diagnoses.columns]

        if "icd_code" not in diagnoses.columns:  # MIMIC-III naming
            diagnoses = diagnoses.rename(
                columns={"icd9_code": "icd_code", "hadm_id": "hadm_id"}
            )
            diagnoses["icd_version"] = "9"

        diagnoses["icd_version"] = (
            pd.to_numeric(diagnoses.get("icd_version"), errors="coerce").fillna(9).astype(int)
        )
        diagnoses = diagnoses.dropna(subset=["hadm_id", "icd_code"])

        rows: Dict[str, Dict[str, bool]] = {}
        for hadm_id, code, version in zip(
            diagnoses["hadm_id"], diagnoses["icd_code"], diagnoses["icd_version"]
        ):
            record = rows.setdefault(str(hadm_id), {})
            for phenotype in PHENOTYPES:
                if phenotype.matches(code, version):
                    record[phenotype.name] = True

        labels = pd.DataFrame.from_dict(rows, orient="index")
        labels.index.name = "patient_id"
        labels = labels.reindex(columns=[p.name for p in PHENOTYPES]).fillna(False)
        labels = labels.astype(bool).reset_index()

        counts = labels[[p.name for p in PHENOTYPES]].sum().sort_values(ascending=False)
        logger.info("Phenotype counts:\n%s", counts[counts > 0].to_string())
        return labels

    def attach(self, cohort: pd.DataFrame) -> pd.DataFrame:
        """Join phenotype labels onto an existing cohort.

        Admissions with no GI code get False rather than NaN — absence of a
        code is evidence of absence here, subject to the under-coding caveat
        above.
        """
        labels = self.load_labels()
        cohort = cohort.copy()
        cohort["patient_id"] = cohort["patient_id"].astype(str)

        merged = cohort.merge(labels, on="patient_id", how="left")
        for phenotype in PHENOTYPES:
            merged[phenotype.name] = merged[phenotype.name].fillna(False).astype(bool)

        merged["any_gi_diagnosis"] = merged[[p.name for p in PHENOTYPES]].any(axis=1)
        logger.info(
            "Attached GI labels: %d of %d admissions carry at least one GI code",
            int(merged["any_gi_diagnosis"].sum()), len(merged),
        )
        return merged


def summarize_phenotypes(cohort: pd.DataFrame) -> pd.DataFrame:
    """Prevalence of each phenotype in a labelled cohort."""
    names = [p.name for p in PHENOTYPES if p.name in cohort.columns]
    summary = pd.DataFrame(
        {
            "n": [int(cohort[name].sum()) for name in names],
            "prevalence": [float(cohort[name].mean()) for name in names],
            "description": [
                next(p.description for p in PHENOTYPES if p.name == name)
                for name in names
            ],
        },
        index=names,
    )
    return summary.sort_values("n", ascending=False)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    root = sys.argv[1] if len(sys.argv) > 1 else "."

    labels = GastroCohortBuilder(root).load_labels()
    print(f"\n{len(labels)} admissions with any diagnosis code")
    print(summarize_phenotypes(labels).to_string())
