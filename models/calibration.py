"""Probability calibration.

A gradient-boosted model optimized for ranking (AUC) produces scores that
separate classes well but are not probabilities: a score of 0.8 does not mean
80% of such patients deteriorate. For a clinical alert that distinction is the
whole ballgame, because thresholds and expected-value decisions are set on
calibrated risk. Calibration is fitted on held-out data — fitting it on the
training fold reproduces the model's own overconfidence.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

logger = logging.getLogger(__name__)


class ProbabilityCalibrator:
    """Maps raw model scores onto calibrated probabilities."""

    def __init__(self, method: Literal["isotonic", "platt"] = "isotonic"):
        self.method = method
        self._model: Optional[object] = None

    def fit(self, scores: np.ndarray, y: np.ndarray) -> "ProbabilityCalibrator":
        scores = np.asarray(scores, dtype=float).ravel()
        y = np.asarray(y).ravel()

        if self.method == "isotonic":
            # Isotonic is non-parametric and can fit any monotone distortion,
            # but it needs enough points not to just memorize the calibration
            # set; below ~1000 samples Platt's two parameters generalize better.
            if len(scores) < 1000:
                logger.info(
                    "Only %d calibration samples; using Platt scaling instead "
                    "of isotonic to avoid overfitting the calibration curve.",
                    len(scores),
                )
                self.method = "platt"
            else:
                model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
                model.fit(scores, y)
                self._model = model
                return self

        model = LogisticRegression(C=1e10, solver="lbfgs")
        model.fit(scores.reshape(-1, 1), y)
        self._model = model
        return self

    def transform(self, scores: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise ValueError("Calibrator must be fitted first")

        scores = np.asarray(scores, dtype=float).ravel()
        if isinstance(self._model, IsotonicRegression):
            return self._model.predict(scores)
        return self._model.predict_proba(scores.reshape(-1, 1))[:, 1]

    def export(self) -> dict:
        """Serialize to a form the WASM runtime can evaluate.

        Isotonic becomes its breakpoint table (piecewise-linear interpolation);
        Platt becomes a two-parameter sigmoid.
        """
        if self._model is None:
            raise ValueError("Calibrator must be fitted first")

        if isinstance(self._model, IsotonicRegression):
            return {
                "method": "isotonic",
                "x": self._model.X_thresholds_.tolist(),
                "y": self._model.y_thresholds_.tolist(),
            }

        return {
            "method": "platt",
            "coef": float(self._model.coef_[0][0]),
            "intercept": float(self._model.intercept_[0]),
        }
