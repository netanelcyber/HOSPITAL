"""Interoperability with PenuX (github.com/netanelcyber/penux).

PenuX is the predecessor system: a single-file, pandas-free, PyTorch-first
pipeline that predicts pathogen class from MIMIC-III/IV. PenuX-II predicts a
different outcome (clinical deterioration) from a different signal (the lab
panel), so the two do not share a model — but they should not disagree about
*where the data lives* or *which window counts*, because a cohort assembled
under one convention is not comparable to one assembled under the other.

This module reuses PenuX's conventions rather than inventing parallel ones:

- `MIMIC_AUTOROOTS` and the same default search paths for dataset discovery
- the same MIMIC-III vs MIMIC-IV layout detection (`hosp/`+`icu/` vs
  top-level `ADMISSIONS.csv`)
- `HOURS_WINDOW` for the observation window, and `SEED`
- `_sanitize_tag`'s naming scheme, so artifacts from both systems sort together

Deliberate departures, and why:

- **pandas is used here.** PenuX forbids it and streams CSVs by hand. That
  constraint buys a dependency-free single file; PenuX-II instead pools seven
  heterogeneous sources with differing schemas and units, where the join and
  reshape logic is the substance of the work. Reimplementing it by hand would
  add risk without removing a real dependency.
- **Tree ensembles, not PyTorch.** Labs are tabular with informative
  missingness, which gradient-boosted trees handle natively and which a neural
  net needs imputation to accept — and imputing a lab that was never ordered
  discards the fact that the clinician did not order it.

The single-file constraint is honoured where it actually matters for
deployment: `web/penux2.html` is one self-contained file.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .public_datasets import (
    ADAPTERS,
    DeteriorationLabelConfig,
    MultiSourceCohortBuilder,
)

logger = logging.getLogger(__name__)


# PenuX's defaults, read from the same environment variables so a run
# configured for one system lands on the same cohort in the other.
SEED = int(os.environ.get("SEED", "42"))
HOURS_WINDOW = int(os.environ.get("HOURS_WINDOW", "24"))
PREDICTION_HORIZON = int(os.environ.get("PREDICTION_HORIZON", "48"))


def sanitize_tag(value: str) -> str:
    """PenuX's `_sanitize_tag`, reproduced so artifact names match exactly."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "dataset"


def looks_like_mimic4_root(root: Path) -> bool:
    return (root / "hosp").exists() and (root / "icu").exists()


def looks_like_mimic3_root(root: Path) -> bool:
    return any(
        (root / name).exists()
        for name in (
            "ADMISSIONS.csv", "ADMISSIONS.csv.gz",
            "admissions.csv", "admissions.csv.gz",
        )
    )


@dataclass(frozen=True)
class DiscoveredRoot:
    """A dataset directory plus the adapter that can read it."""

    path: Path
    source: str  # key into public_datasets.ADAPTERS
    tag: str     # PenuX-style artifact tag

    def __repr__(self) -> str:
        return f"DiscoveredRoot({self.source}, {self.tag}, {self.path})"


def discover_dataset_roots(
    extra_roots: Optional[List[str | Path]] = None,
    search_base: Optional[str | Path] = None,
) -> List[DiscoveredRoot]:
    """Find MIMIC roots using PenuX's search order.

    Order: `MIMIC_AUTOROOTS`, then PenuX's two hard-coded demo locations, then
    a recursive scan of `dataset/mimic`. Explicit configuration wins over
    discovery, which is what makes a run reproducible.

    Args:
        extra_roots: additional directories to consider first
        search_base: root to scan instead of the current working directory,
            e.g. a PenuX checkout
    """
    base = Path(search_base) if search_base else Path.cwd()
    candidates: List[Path] = []

    for root in extra_roots or []:
        candidates.append(Path(root))

    env = os.environ.get("MIMIC_AUTOROOTS", "").strip()
    if env:
        candidates.extend(Path(part.strip()) for part in env.split(",") if part.strip())

    # PenuX's hard-coded demo paths, resolved relative to the search base.
    candidates.append(
        base
        / "datasets/datasets/montassarba/mimic-iv-clinical-database-demo-2-2"
        / "versions/1/mimic-iv-clinical-database-demo-2.2"
    )
    candidates.append(base / "mimic-iv-clinical-database-demo-2.2")

    mimic_base = base / "dataset" / "mimic"
    if mimic_base.is_dir():
        candidates.append(mimic_base)
        candidates.extend(
            p for p in list(mimic_base.glob("*")) + list(mimic_base.glob("*/*")) if p.is_dir()
        )

    discovered: List[DiscoveredRoot] = []
    seen: set[Path] = set()

    for candidate in candidates:
        if not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue

        if looks_like_mimic4_root(candidate):
            source = "mimic-iv"
        elif looks_like_mimic3_root(candidate):
            source = "mimic-iii"
        else:
            continue

        seen.add(resolved)
        discovered.append(
            DiscoveredRoot(path=candidate, source=source, tag=sanitize_tag(candidate.name))
        )

    logger.info("Discovered %d dataset root(s)", len(discovered))
    for root in discovered:
        logger.info("  %s -> %s", root.tag, root.source)
    return discovered


def label_config_from_env() -> DeteriorationLabelConfig:
    """Build the label window from PenuX's environment variables."""
    return DeteriorationLabelConfig(
        observation_hours=float(HOURS_WINDOW),
        prediction_horizon_hours=float(PREDICTION_HORIZON),
    )


def build_cohort_from_discovery(
    extra_roots: Optional[List[str | Path]] = None,
    search_base: Optional[str | Path] = None,
    label_config: Optional[DeteriorationLabelConfig] = None,
) -> pd.DataFrame:
    """Discover every available MIMIC root and pool it into one cohort.

    Raises when nothing is found, rather than silently falling back to
    synthetic data — a model quietly trained on invented patients is worse
    than a failed run.
    """
    roots = discover_dataset_roots(extra_roots, search_base)
    if not roots:
        raise FileNotFoundError(
            "No MIMIC dataset root found. Set MIMIC_AUTOROOTS to a directory "
            "containing either hosp/+icu/ (MIMIC-IV) or ADMISSIONS.csv "
            "(MIMIC-III), or pass search_base pointing at a PenuX checkout."
        )

    builder = MultiSourceCohortBuilder(label_config or label_config_from_env())
    for root in roots:
        builder.add(root.source, root.path)

    cohort = builder.build(skip_missing=True)
    cohort.attrs["roots"] = [str(r.path) for r in roots]
    cohort.attrs["tags"] = [r.tag for r in roots]
    return cohort


def artifact_name(kind: str, tags: List[str], suffix: str = "png") -> str:
    """Name an artifact the way PenuX does: `kind__tag1_tag2__extra.ext`.

    PenuX writes e.g. `calibration__mimic4_..._demo_2_2__gelu.png`; matching
    the scheme keeps both systems' outputs interleaved in a directory listing
    instead of forming two unrelated groups.
    """
    joined = "_".join(sanitize_tag(t) for t in tags) or "dataset"
    return f"{sanitize_tag(kind)}__{joined}.{suffix}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    import sys

    base = sys.argv[1] if len(sys.argv) > 1 else None
    roots = discover_dataset_roots(search_base=base)
    for root in roots:
        print(root)

    if roots:
        cohort = build_cohort_from_discovery(search_base=base)
        print(f"\nPooled cohort: {cohort.shape}")
        print(MultiSourceCohortBuilder.site_summary(cohort))
