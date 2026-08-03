"""Export a trained pipeline to a self-contained bundle the WASM runtime scores.

Why export rather than serve: patient labs are the most sensitive data a
hospital holds, and the safest request is the one never sent. Shipping the
model to the browser means the bundle crosses the network once, and lab values
never leave the machine they were entered on. It also removes the API from the
latency path and lets scoring work when the network doesn't.

The bundle is a single JSON document containing the preprocessing constants,
the flattened decision trees, and the calibration curve. It carries no code —
the WASM module is the only executable part, and it is compiled separately —
so a bundle from an untrusted source can corrupt a prediction but cannot
execute anything.

Tree layout
-----------
Each tree is four parallel arrays indexed by node id, which is what makes the
Rust side a tight loop over slices instead of a pointer chase:

    feature[i]   feature index tested at node i, or -1 at a leaf
    threshold[i] comparison value; go left when x < threshold
    left[i]      left child index, or -1 at a leaf
    right[i]     right child index, or -1 at a leaf
    value[i]     leaf contribution (log-odds), unused at internal nodes
    missing[i]   child to take when the feature is NaN
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

BUNDLE_FORMAT_VERSION = 1


class TreeExportError(RuntimeError):
    """Raised when a backend's trees cannot be flattened."""


# ---------------------------------------------------------------------------
# Per-backend tree extraction
# ---------------------------------------------------------------------------

def _export_sklearn_histgb(model, feature_names: List[str]) -> Dict:
    """Flatten sklearn HistGradientBoostingClassifier."""
    trees = []
    for stage in model._predictors:
        for predictor in stage:
            nodes = predictor.nodes
            n = len(nodes)
            feature = np.full(n, -1, dtype=np.int32)
            threshold = np.zeros(n, dtype=np.float64)
            left = np.full(n, -1, dtype=np.int32)
            right = np.full(n, -1, dtype=np.int32)
            value = np.zeros(n, dtype=np.float64)
            missing = np.full(n, -1, dtype=np.int32)

            for i, node in enumerate(nodes):
                if node["is_leaf"]:
                    value[i] = node["value"]
                    continue
                feature[i] = node["feature_idx"]
                threshold[i] = node["num_threshold"]
                left[i] = node["left"]
                right[i] = node["right"]
                missing[i] = node["left"] if node["missing_go_to_left"] else node["right"]

            trees.append(
                {
                    "feature": feature.tolist(),
                    "threshold": threshold.tolist(),
                    "left": left.tolist(),
                    "right": right.tolist(),
                    "value": value.tolist(),
                    "missing": missing.tolist(),
                }
            )

    return {
        "trees": trees,
        "base_score": float(np.ravel(model._baseline_prediction)[0]),
        # HistGB folds the learning rate into the leaf values already.
        "learning_rate": 1.0,
        "n_features": len(feature_names),
        # sklearn takes the left branch on `x <= threshold`, unlike XGBoost's
        # strict `<`. Off-by-one on the boundary silently shifts predictions.
        "split_inclusive": True,
    }


def _export_xgboost(model, feature_names: List[str]) -> Dict:
    """Flatten an XGBClassifier via its JSON dump."""
    booster = model.get_booster()
    dumps = booster.get_dump(dump_format="json")
    name_to_index = {name: i for i, name in enumerate(feature_names)}

    trees = []
    for raw in dumps:
        node_list: List[dict] = []
        _flatten_xgb_node(json.loads(raw), node_list)

        n = len(node_list)
        feature = np.full(n, -1, dtype=np.int32)
        threshold = np.zeros(n, dtype=np.float64)
        left = np.full(n, -1, dtype=np.int32)
        right = np.full(n, -1, dtype=np.int32)
        value = np.zeros(n, dtype=np.float64)
        missing = np.full(n, -1, dtype=np.int32)

        for i, node in enumerate(node_list):
            if "leaf" in node:
                value[i] = node["leaf"]
                continue
            raw_split = node["split"]
            # XGBoost dumps either "f3" or the original column name.
            if isinstance(raw_split, str) and raw_split.startswith("f") and raw_split[1:].isdigit():
                feature[i] = int(raw_split[1:])
            else:
                feature[i] = name_to_index[raw_split]
            threshold[i] = node["split_condition"]
            left[i] = node["_left"]
            right[i] = node["_right"]
            missing[i] = node["_missing"]

        trees.append(
            {
                "feature": feature.tolist(),
                "threshold": threshold.tolist(),
                "left": left.tolist(),
                "right": right.tolist(),
                "value": value.tolist(),
                "missing": missing.tolist(),
            }
        )

    base_score = 0.0
    config = json.loads(booster.save_config())
    try:
        base_score = float(config["learner"]["learner_model_param"]["base_score"])
    except (KeyError, ValueError):
        base_score = 0.5

    # base_score is a probability; the tree sum lives in log-odds space.
    base_score = float(np.clip(base_score, 1e-6, 1 - 1e-6))
    return {
        "trees": trees,
        "base_score": float(np.log(base_score / (1 - base_score))),
        "learning_rate": 1.0,
        "n_features": len(feature_names),
    }


def _flatten_xgb_node(node: dict, out: List[dict]) -> int:
    """Depth-first flatten of XGBoost's nested JSON into indexed nodes."""
    index = len(out)
    record = dict(node)
    out.append(record)

    if "leaf" in node:
        return index

    children = {child["nodeid"]: child for child in node["children"]}
    record["_left"] = _flatten_xgb_node(children[node["yes"]], out)
    record["_right"] = _flatten_xgb_node(children[node["no"]], out)
    record["_missing"] = (
        record["_left"] if node["missing"] == node["yes"] else record["_right"]
    )
    # Drop the nested payload so the flattened record stays small.
    record.pop("children", None)
    return index


def _export_lightgbm(model, feature_names: List[str]) -> Dict:
    """Flatten an LGBMClassifier via dump_model."""
    dumped = model.booster_.dump_model()
    trees = []

    for tree_info in dumped["tree_info"]:
        node_list: List[dict] = []
        _flatten_lgb_node(tree_info["tree_structure"], node_list)

        n = len(node_list)
        feature = np.full(n, -1, dtype=np.int32)
        threshold = np.zeros(n, dtype=np.float64)
        left = np.full(n, -1, dtype=np.int32)
        right = np.full(n, -1, dtype=np.int32)
        value = np.zeros(n, dtype=np.float64)
        missing = np.full(n, -1, dtype=np.int32)

        for i, node in enumerate(node_list):
            if "leaf_value" in node:
                value[i] = node["leaf_value"]
                continue
            feature[i] = node["split_feature"]
            threshold[i] = node["threshold"]
            left[i] = node["_left"]
            right[i] = node["_right"]
            missing[i] = node["_missing"]

        trees.append(
            {
                "feature": feature.tolist(),
                "threshold": threshold.tolist(),
                "left": left.tolist(),
                "right": right.tolist(),
                "value": value.tolist(),
                "missing": missing.tolist(),
            }
        )

    return {
        "trees": trees,
        "base_score": 0.0,
        "learning_rate": 1.0,
        "n_features": len(feature_names),
        # LightGBM splits on <=, unlike the < used by the other backends.
        "split_inclusive": True,
    }


def _flatten_lgb_node(node: dict, out: List[dict]) -> int:
    index = len(out)
    record = dict(node)
    out.append(record)

    if "leaf_value" in node and "split_feature" not in node:
        return index

    record["_left"] = _flatten_lgb_node(node["left_child"], out)
    record["_right"] = _flatten_lgb_node(node["right_child"], out)
    # default_left says which side a missing value follows.
    record["_missing"] = record["_left"] if node.get("default_left") else record["_right"]
    record.pop("left_child", None)
    record.pop("right_child", None)
    return index


_EXPORTERS = {
    "sklearn": _export_sklearn_histgb,
    "xgboost": _export_xgboost,
    "lightgbm": _export_lightgbm,
}


# ---------------------------------------------------------------------------
# Bundle assembly
# ---------------------------------------------------------------------------

def export_bundle(
    ensemble,
    lab_extractor=None,
    calibrator=None,
    output_path: str | Path = "wasm/model_bundle.json",
    metadata: Optional[Dict] = None,
) -> Dict:
    """Serialize a fitted pipeline into a browser-scoreable bundle.

    Args:
        ensemble: fitted DeteriorationEnsemble
        lab_extractor: fitted LabFeatureExtractor, for preprocessing constants
        calibrator: fitted ProbabilityCalibrator
        output_path: where to write the JSON bundle
        metadata: free-form provenance recorded alongside the model

    Returns:
        The bundle dict that was written.
    """
    if not getattr(ensemble, "_fitted", False):
        raise ValueError("Ensemble must be fitted before export")

    models = {}
    for name, model in ensemble.models.items():
        exporter = _EXPORTERS.get(name)
        if exporter is None:
            raise TreeExportError(f"No tree exporter for backend {name!r}")
        models[name] = exporter(model, ensemble.feature_names)
        models[name]["weight"] = float(ensemble.weights[name])
        logger.info("Exported %s: %d trees", name, len(models[name]["trees"]))

    bundle: Dict = {
        "format_version": BUNDLE_FORMAT_VERSION,
        "feature_names": list(ensemble.feature_names),
        "models": models,
        "preprocessing": _export_preprocessing(lab_extractor),
        "calibration": calibrator.export() if calibrator is not None else None,
        "metadata": metadata or {},
    }

    _reject_non_finite(bundle)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # allow_nan=False: Python emits bare `NaN`/`Infinity`, which is not valid
    # JSON and which strict parsers (serde, and every browser) reject. Writing
    # it would produce a bundle that only Python can read.
    output_path.write_text(json.dumps(bundle, allow_nan=False))

    size_kb = output_path.stat().st_size / 1024
    logger.info("Wrote %s (%.1f KB)", output_path, size_kb)
    return bundle


def _reject_non_finite(bundle: Dict) -> None:
    """Fail on NaN/Inf in the parts the scorer reads as plain f64.

    A NaN threshold or scaler constant makes every comparison against it false,
    so the tree silently routes every patient down one branch. `metadata` is
    exempt: it holds fixtures where NaN legitimately marks an unmeasured lab,
    and those are serialized as null instead.
    """
    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "metadata":
                    continue
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, float) and not np.isfinite(node):
            raise ValueError(
                f"Non-finite value {node} at {path}; the scorer reads these as "
                "plain f64 and a NaN threshold routes every patient one way."
            )

    walk(bundle, "bundle")


def _json_safe(value):
    """Recursively convert NaN/Inf to None so the value survives strict JSON."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _export_preprocessing(lab_extractor) -> Dict:
    """Export the scaler constants and missing-value fills.

    The browser must reproduce training-time preprocessing exactly; a scaler
    refitted on client data would shift every feature and silently invalidate
    the thresholds baked into the trees.
    """
    if lab_extractor is None or not getattr(lab_extractor, "fitted", False):
        return {"kind": "none"}

    scaler = lab_extractor.scaler
    columns = list(lab_extractor.feature_columns)

    if hasattr(scaler, "mean_"):
        return {
            "kind": "z_score",
            "columns": columns,
            "mean": np.asarray(scaler.mean_, dtype=float).tolist(),
            "scale": np.asarray(scaler.scale_, dtype=float).tolist(),
            "fill": [float(lab_extractor.feature_means.get(c, 0.0)) for c in columns],
        }

    return {
        "kind": "minmax",
        "columns": columns,
        "min": np.asarray(scaler.data_min_, dtype=float).tolist(),
        "scale": np.asarray(scaler.scale_, dtype=float).tolist(),
        "fill": [float(lab_extractor.feature_means.get(c, 0.0)) for c in columns],
    }


def score_bundle(bundle: Dict, features: np.ndarray) -> np.ndarray:
    """Reference implementation of bundle scoring, in NumPy.

    This exists to verify the Rust/WASM implementation against a known-correct
    result: an exported model that scores differently in the browser than in
    training is the failure mode this whole format is meant to prevent, and it
    is invisible without a reference to diff against.
    """
    features = np.atleast_2d(np.asarray(features, dtype=float))
    blended = np.zeros(len(features), dtype=float)

    for spec in bundle["models"].values():
        inclusive = spec.get("split_inclusive", False)
        margins = np.full(len(features), spec["base_score"], dtype=float)

        for tree in spec["trees"]:
            feature = np.asarray(tree["feature"], dtype=np.int64)
            threshold = np.asarray(tree["threshold"], dtype=float)
            left = np.asarray(tree["left"], dtype=np.int64)
            right = np.asarray(tree["right"], dtype=np.int64)
            value = np.asarray(tree["value"], dtype=float)
            missing = np.asarray(tree["missing"], dtype=np.int64)

            for row_index, row in enumerate(features):
                node = 0
                while feature[node] >= 0:
                    x = row[feature[node]]
                    if np.isnan(x):
                        node = missing[node]
                    elif (x <= threshold[node]) if inclusive else (x < threshold[node]):
                        node = left[node]
                    else:
                        node = right[node]
                margins[row_index] += value[node] * spec["learning_rate"]

        blended += spec["weight"] / (1.0 + np.exp(-margins))

    calibration = bundle.get("calibration")
    if calibration is None:
        return blended

    if calibration["method"] == "isotonic":
        return np.interp(blended, calibration["x"], calibration["y"])

    logits = calibration["coef"] * blended + calibration["intercept"]
    return 1.0 / (1.0 + np.exp(-logits))
