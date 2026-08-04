"""Build the self-contained single-file PenuX-II page.

Embeds the compiled WASM and the model bundle as base64 into one HTML document,
so the whole application is a single file that runs from `file://` with no
server, no CDN and no network. That is the deployment property that matters
clinically: a page that cannot make requests cannot leak lab values.

The embedded model is trained on **laboratory features only**. The clinical NLP
panel in the page runs its own JavaScript ConText implementation for display and
audit, and its output is deliberately not fed into the score: a JS reimplementation
of the Python featurizer that drifted even slightly would shift every prediction
silently, which is the exact failure the parity test exists to prevent. Labs are
the primary channel by design, so the page scores from them alone.
"""

from __future__ import annotations

import base64
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from inference.wasm_export import export_bundle, score_bundle  # noqa: E402
from models.calibration import ProbabilityCalibrator  # noqa: E402
from models.ensemble import DeteriorationEnsemble  # noqa: E402
from features.lab_features import LabFeatureExtractor  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("build")

PANEL = [
    "glucose", "hemoglobin", "potassium", "sodium", "creatinine",
    "blood_urea_nitrogen", "platelet_count", "white_blood_cell_count",
]


def synthesize_cohort(n: int = 6000, seed: int = 7) -> pd.DataFrame:
    """A stand-in cohort so the page ships with a working model.

    Replace with a real cohort from `data.public_datasets` before any use
    beyond demonstration; these coefficients are invented, not learned from
    patients.
    """
    rng = np.random.default_rng(seed)
    labs = {
        "glucose": rng.normal(115, 40, n),
        "hemoglobin": rng.normal(12.8, 2.1, n),
        "potassium": rng.normal(4.1, 0.65, n),
        "sodium": rng.normal(138, 5.5, n),
        "creatinine": rng.lognormal(0.0, 0.55, n),
        "blood_urea_nitrogen": rng.normal(20, 11, n),
        "platelet_count": rng.normal(245, 80, n),
        "white_blood_cell_count": rng.normal(8.5, 4.5, n),
    }

    logit = (
        -2.6
        + 1.25 * np.log(np.clip(labs["creatinine"], 0.1, None))
        + 0.055 * (labs["white_blood_cell_count"] - 8.5)
        - 0.0045 * (labs["platelet_count"] - 245)
        + 0.020 * (labs["blood_urea_nitrogen"] - 20)
        - 0.085 * (labs["hemoglobin"] - 12.8)
        + 0.030 * np.abs(labs["sodium"] - 138)
    )
    y = rng.binomial(1, 1 / (1 + np.exp(-logit)))

    cohort = pd.DataFrame({"deteriorated": y})
    for name, values in labs.items():
        cohort[f"lab_{name}"] = values

    # Real panels are incomplete, and which tests were ordered is informative.
    for name in ("blood_urea_nitrogen", "platelet_count"):
        mask = rng.random(n) < 0.15
        cohort.loc[mask, f"lab_{name}"] = np.nan

    return cohort


def load_real_cohort(search_base: str | None) -> pd.DataFrame | None:
    """Pool the MIMIC demo subsets if they can be found.

    The demo subsets are openly licensed, unlike the full datasets, so a model
    trained on them can ship. They are small (hundreds of stays), which limits
    what the resulting numbers mean — but they are real patients.
    """
    if not search_base:
        return None
    try:
        from data.penux_compat import build_cohort_from_discovery

        cohort = build_cohort_from_discovery(search_base=search_base)
    except (FileNotFoundError, ValueError) as exc:
        logger.info("No real cohort available (%s)", exc)
        return None

    keep = ["deteriorated"] + [f"lab_{name}" for name in PANEL]
    missing = [c for c in keep if c not in cohort.columns]
    if missing:
        logger.info("Real cohort lacks %s; falling back to synthetic", missing)
        return None

    subset = cohort[keep].copy()
    subset["deteriorated"] = subset["deteriorated"].astype(int)
    if subset["deteriorated"].nunique() < 2:
        return None
    return subset


def train_bundle(search_base: str | None = None) -> dict:
    real = load_real_cohort(search_base)
    if real is not None:
        cohort = real.sample(frac=1.0, random_state=7).reset_index(drop=True)
        provenance = "mimic-iii-demo + mimic-iv-demo (real patients)"
        logger.info("Training on %d real stays", len(cohort))
    else:
        cohort = synthesize_cohort()
        provenance = "synthetic"
        logger.info("Training on synthetic data")

    y = cohort["deteriorated"].to_numpy()

    split = int(0.7 * len(cohort))
    train, val = cohort.iloc[:split], cohort.iloc[split:]

    extractor = LabFeatureExtractor()
    X_train = extractor.fit_transform(train).drop(columns=["deteriorated"])
    X_val = extractor.transform(val).drop(columns=["deteriorated"])
    X_train = X_train.select_dtypes(include=[np.number])
    X_val = X_val[X_train.columns]

    # Parameters scale with cohort size. The library defaults are tuned for a
    # million stays, where min_samples_leaf=50 and early stopping on a 10%
    # split are right; applied to a few hundred rows the same settings stop
    # after ~25 trees and score below chance. Tuning at one scale and shipping
    # to another is its own bug class, so the size is read here explicitly.
    small = len(cohort) < 20_000
    leaf = 5 if small else 50
    tree_params = {
        "max_depth": 4,
        "min_samples_leaf": leaf,
        "early_stopping": not small,
    }
    logger.info(
        "Cohort of %d -> %s regime (min_samples_leaf=%d, early_stopping=%s)",
        len(cohort), "small-data" if small else "large-data", leaf, not small,
    )

    # Fewer, shallower trees than the training default: the bundle ships to
    # every browser, so size is a first-class constraint here.
    ensemble = DeteriorationEnsemble(
        backends=("xgboost", "lightgbm"),
        params={
            "xgboost": {"n_estimators": 120, "max_depth": 4, "min_child_weight": leaf},
            "lightgbm": {"n_estimators": 120, "max_depth": 4, "min_child_samples": leaf},
            "sklearn": {"max_iter": 120, **tree_params},
        },
    )
    ensemble.fit(X_train, y[:split])

    calibrator = ProbabilityCalibrator(method="isotonic")
    calibrator.fit(ensemble.predict_proba(X_val), y[split:])

    from sklearn.metrics import average_precision_score, roc_auc_score

    scores = ensemble.predict_proba(X_val)
    auc = float(roc_auc_score(y[split:], scores))
    ap = float(average_precision_score(y[split:], scores))
    logger.info(
        "Embedded model: AUC=%.3f  AP=%.3f  event rate=%.1f%%",
        roc_auc_score(y[split:], scores),
        average_precision_score(y[split:], scores),
        100 * y[split:].mean(),
    )

    bundle = export_bundle(
        ensemble,
        extractor,
        calibrator,
        output_path=ROOT / "wasm" / "page_bundle.json",
        metadata={
            "trained_on": provenance,
            "panel": PANEL,
            "n_train": int(split),
            "n_val": int(len(cohort) - split),
            "val_auc": auc,
            "val_ap": ap,
            "note": "Research model. Demo-subset cohorts are small; metrics "
                    "do not establish clinical performance.",
        },
    )

    # The page must reproduce these numbers; a drift here is a shipped bug.
    # Rows are taken already-scaled, so the page scores them with preprocessing
    # skipped — applying the scaler twice is silent and merely wrong.
    fixture = X_val.head(8).to_numpy()
    reference = score_bundle(bundle, fixture)

    from inference.wasm_export import _json_safe

    bundle["metadata"]["self_test"] = {
        "features": _json_safe(fixture.tolist()),
        "expected": reference.tolist(),
    }

    # Rewrite so the file on disk carries the fixture the page validates against.
    (ROOT / "wasm" / "page_bundle.json").write_text(json.dumps(bundle, allow_nan=False))
    return bundle


def build(search_base: str | None = None) -> Path:
    wasm_path = (
        ROOT / "wasm" / "target" / "wasm32-unknown-unknown" / "release" / "penux_scorer.wasm"
    )
    if not wasm_path.exists():
        raise SystemExit(
            f"{wasm_path} not found. Build it first:\n"
            "  cd wasm && cargo build --release --target wasm32-unknown-unknown --lib"
        )

    bundle = train_bundle(search_base)
    template = (ROOT / "web" / "template.html").read_text()

    wasm_b64 = base64.b64encode(wasm_path.read_bytes()).decode()
    bundle_b64 = base64.b64encode(json.dumps(bundle).encode()).decode()

    html = template.replace("__WASM_BASE64__", wasm_b64).replace(
        "__BUNDLE_BASE64__", bundle_b64
    )

    output = ROOT / "web" / "penux2.html"
    output.write_text(html)
    logger.info(
        "Wrote %s (%.0f KB: wasm %.0f KB, model %.0f KB)",
        output,
        output.stat().st_size / 1024,
        len(wasm_b64) / 1024,
        len(bundle_b64) / 1024,
    )
    return output


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else None)
