"""End-to-end training: cohort -> features -> model -> calibration -> bundle."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit, train_test_split

from features.clinical_nlp import ClinicalNLPFeaturizer
from features.clinical_reference import LoincHarmonizer
from features.lab_features import LabFeatureExtractor
from models.calibration import ProbabilityCalibrator
from models.ensemble import DeteriorationEnsemble

logger = logging.getLogger(__name__)


@dataclass
class SplitData:
    """A three-way split. Calibration needs data the model never saw."""

    X_train: pd.DataFrame
    y_train: np.ndarray
    X_val: pd.DataFrame
    y_val: np.ndarray
    X_test: pd.DataFrame
    y_test: np.ndarray


@dataclass
class TrainingResult:
    ensemble: DeteriorationEnsemble
    calibrator: ProbabilityCalibrator
    lab_extractor: LabFeatureExtractor
    metrics: Dict[str, float]
    feature_importance: pd.DataFrame


class TrainingPipeline:
    """Trains a deterioration model from a cohort frame."""

    def __init__(
        self,
        use_clinical_nlp: bool = True,
        harmonize_units: bool = True,
        backends: Tuple[str, ...] = ("xgboost", "lightgbm"),
        calibration_method: str = "isotonic",
        random_state: int = 42,
    ):
        self.use_clinical_nlp = use_clinical_nlp
        self.harmonize_units = harmonize_units
        self.backends = backends
        self.calibration_method = calibration_method
        self.random_state = random_state

        self.lab_extractor = LabFeatureExtractor()
        self.nlp_featurizer = ClinicalNLPFeaturizer() if use_clinical_nlp else None
        self.harmonizer = LoincHarmonizer() if harmonize_units else None

    # -- feature construction -----------------------------------------------

    def build_features(
        self, cohort: pd.DataFrame, fit: bool = False
    ) -> pd.DataFrame:
        """Turn a raw cohort into the model's feature matrix."""
        frame = cohort.copy()

        if self.harmonizer is not None:
            frame = self.harmonizer.harmonize_frame(frame)

        if self.nlp_featurizer is not None and "medical_report" in frame.columns:
            frame = (
                self.nlp_featurizer.fit_transform(frame)
                if fit
                else self.nlp_featurizer.transform(frame)
            )

        frame = (
            self.lab_extractor.fit_transform(frame)
            if fit
            else self.lab_extractor.transform(frame)
        )

        drop = {"patient_id", "medical_report", "deteriorated", "timestamp",
                "source", "series", "series_title", "outcome_source_column"}
        features = frame[[c for c in frame.columns if c not in drop]]
        return features.select_dtypes(include=[np.number])

    # -- splitting -----------------------------------------------------------

    def split(
        self,
        cohort: pd.DataFrame,
        groups: Optional[pd.Series] = None,
        test_size: float = 0.15,
        val_size: float = 0.15,
    ) -> SplitData:
        """Split into train/val/test.

        When `groups` is given (a site, or a patient with several admissions),
        splitting is grouped: the same patient appearing in train and test lets
        the model recognize them rather than generalize, and inflates every
        metric.
        """
        y = cohort["deteriorated"].astype(int).to_numpy()
        indices = np.arange(len(cohort))

        if groups is not None:
            splitter = GroupShuffleSplit(
                n_splits=1, test_size=test_size, random_state=self.random_state
            )
            rest_idx, test_idx = next(splitter.split(indices, y, groups))
            inner_groups = groups.iloc[rest_idx]
            inner = GroupShuffleSplit(
                n_splits=1,
                test_size=val_size / (1 - test_size),
                random_state=self.random_state,
            )
            train_pos, val_pos = next(
                inner.split(rest_idx, y[rest_idx], inner_groups)
            )
            train_idx, val_idx = rest_idx[train_pos], rest_idx[val_pos]
        else:
            rest_idx, test_idx = train_test_split(
                indices, test_size=test_size, stratify=y,
                random_state=self.random_state,
            )
            train_idx, val_idx = train_test_split(
                rest_idx,
                test_size=val_size / (1 - test_size),
                stratify=y[rest_idx],
                random_state=self.random_state,
            )

        # Features are fitted on the training rows only; fitting the scaler or
        # the imputation means on the full cohort leaks test statistics.
        train_cohort = cohort.iloc[train_idx]
        X_train = self.build_features(train_cohort, fit=True)
        X_val = self.build_features(cohort.iloc[val_idx], fit=False)
        X_test = self.build_features(cohort.iloc[test_idx], fit=False)

        return SplitData(
            X_train=X_train,
            y_train=y[train_idx],
            X_val=X_val,
            y_val=y[val_idx],
            X_test=X_test,
            y_test=y[test_idx],
        )

    # -- training ------------------------------------------------------------

    def train(
        self, cohort: pd.DataFrame, groups: Optional[pd.Series] = None
    ) -> TrainingResult:
        if "deteriorated" not in cohort.columns:
            raise ValueError("Cohort must carry a 'deteriorated' column")

        data = self.split(cohort, groups=groups)
        logger.info(
            "Split: train=%d val=%d test=%d, event rate %.1f%%",
            len(data.X_train), len(data.X_val), len(data.X_test),
            100 * data.y_train.mean(),
        )

        ensemble = DeteriorationEnsemble(
            backends=self.backends, random_state=self.random_state
        )
        ensemble.fit(data.X_train, data.y_train, eval_set=(data.X_val, data.y_val))

        # Calibrate on validation: the model is overconfident on the fold it
        # was fitted to, and calibrating there would learn the wrong curve.
        calibrator = ProbabilityCalibrator(method=self.calibration_method)
        calibrator.fit(ensemble.predict_proba(data.X_val), data.y_val)

        metrics = self.evaluate(ensemble, calibrator, data)

        return TrainingResult(
            ensemble=ensemble,
            calibrator=calibrator,
            lab_extractor=self.lab_extractor,
            metrics=metrics,
            # Validation data is passed so the permutation fallback can run when
            # the fitted backend reports no native importances.
            feature_importance=ensemble.feature_importance(data.X_val, data.y_val),
        )

    def evaluate(
        self,
        ensemble: DeteriorationEnsemble,
        calibrator: ProbabilityCalibrator,
        data: SplitData,
    ) -> Dict[str, float]:
        """Score on held-out test data."""
        raw = ensemble.predict_proba(data.X_test)
        calibrated = calibrator.transform(raw)
        y = data.y_test

        metrics = {
            "roc_auc": float(roc_auc_score(y, raw)),
            # Average precision is the metric that matters for a rare outcome:
            # ROC-AUC stays flattering when the positives are a small minority.
            "average_precision": float(average_precision_score(y, raw)),
            "brier_raw": float(brier_score_loss(y, raw)),
            "brier_calibrated": float(brier_score_loss(y, calibrated)),
            "event_rate": float(y.mean()),
            "n_test": int(len(y)),
        }

        metrics.update(self._alert_metrics(y, calibrated))
        logger.info("Test metrics: %s", json.dumps(metrics, indent=2))
        return metrics

    @staticmethod
    def _alert_metrics(y: np.ndarray, scores: np.ndarray) -> Dict[str, float]:
        """Sensitivity and alert burden at a clinically usable threshold.

        A deterioration alert is only adopted if the ward can act on its volume;
        recall at a fixed alert rate says more about that than AUC does.
        """
        results: Dict[str, float] = {}
        for alert_rate in (0.05, 0.10, 0.20):
            threshold = float(np.quantile(scores, 1 - alert_rate))
            flagged = scores >= threshold
            positives = y.sum()
            results[f"recall_at_{int(alert_rate * 100)}pct_alerts"] = (
                float((flagged & (y == 1)).sum() / positives) if positives else 0.0
            )
            results[f"precision_at_{int(alert_rate * 100)}pct_alerts"] = (
                float((flagged & (y == 1)).sum() / flagged.sum()) if flagged.sum() else 0.0
            )
        return results

    # -- site-aware validation ----------------------------------------------

    def leave_one_site_out(self, cohort: pd.DataFrame) -> pd.DataFrame:
        """Train on all sites but one, test on the held-out site.

        This is the honest test for a pooled multi-source cohort. A model can
        score well on a shuffled split purely by learning each site's assay
        quirks, and then fail at the first hospital it has not seen.
        """
        if "source" not in cohort.columns:
            raise ValueError("leave_one_site_out requires a 'source' column")

        rows = []
        for site in sorted(cohort["source"].unique()):
            train_cohort = cohort[cohort["source"] != site]
            test_cohort = cohort[cohort["source"] == site]

            if train_cohort["deteriorated"].nunique() < 2 or len(test_cohort) < 50:
                logger.warning("Skipping site %s: insufficient data", site)
                continue

            pipeline = TrainingPipeline(
                use_clinical_nlp=self.use_clinical_nlp,
                harmonize_units=self.harmonize_units,
                backends=self.backends,
                random_state=self.random_state,
            )
            X_train = pipeline.build_features(train_cohort, fit=True)
            X_test = pipeline.build_features(test_cohort, fit=False)
            y_train = train_cohort["deteriorated"].astype(int).to_numpy()
            y_test = test_cohort["deteriorated"].astype(int).to_numpy()

            ensemble = DeteriorationEnsemble(
                backends=self.backends, random_state=self.random_state
            )
            ensemble.fit(X_train, y_train)
            scores = ensemble.predict_proba(X_test)

            rows.append(
                {
                    "held_out_site": site,
                    "n_test": len(y_test),
                    "event_rate": float(y_test.mean()),
                    "roc_auc": float(roc_auc_score(y_test, scores))
                    if len(np.unique(y_test)) > 1
                    else float("nan"),
                    "average_precision": float(average_precision_score(y_test, scores))
                    if len(np.unique(y_test)) > 1
                    else float("nan"),
                }
            )

        return pd.DataFrame(rows)
