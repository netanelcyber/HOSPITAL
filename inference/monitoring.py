"""Production monitoring for model performance and patient safety.

Tracks model drift, calibration degradation, per-site performance, and alert
generation based on risk thresholds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import deque
from datetime import datetime, timedelta

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RiskAlert:
    """Patient safety alert triggered by risk thresholds."""

    patient_id: str
    timestamp: datetime
    risk_level: str  # "low", "moderate", "high", "critical"
    predicted_risk: float  # 0.0 to 1.0
    alert_type: str  # "deterioration", "sepsis", "aki", etc.
    recommendation: str
    audit_trail: List[str] = field(default_factory=list)


@dataclass
class ModelPerformanceMetrics:
    """Tracks model performance on recent predictions."""

    window_size: int  # predictions tracked (default 100)
    predictions: deque = field(default_factory=lambda: deque(maxlen=100))
    actuals: deque = field(default_factory=lambda: deque(maxlen=100))

    def add(self, prediction: float, actual: Optional[int]) -> None:
        """Record a prediction-outcome pair."""
        self.predictions.append(prediction)
        if actual is not None:
            self.actuals.append(actual)

    def compute_auc(self) -> Optional[float]:
        """Rough AUC estimate on recent window."""
        if len(self.actuals) < 10:
            return None
        from sklearn.metrics import roc_auc_score

        try:
            return float(roc_auc_score(self.actuals, self.predictions))
        except Exception as e:
            logger.warning("AUC computation failed: %s", e)
            return None

    def compute_calibration(self) -> Optional[Dict[str, float]]:
        """Check if predicted probabilities match observed frequencies."""
        if len(self.actuals) < 20:
            return None

        # Bin predictions and compute observed frequency in each bin
        bins = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        calibration_errors = []

        for i in range(len(bins) - 1):
            mask = np.array(self.predictions) >= bins[i]
            mask &= np.array(self.predictions) < bins[i + 1]
            if mask.sum() > 0:
                observed_freq = np.array(self.actuals)[mask].mean()
                expected_freq = (bins[i] + bins[i + 1]) / 2
                error = abs(observed_freq - expected_freq)
                calibration_errors.append(error)

        if not calibration_errors:
            return None

        return {
            "mean_calibration_error": float(np.mean(calibration_errors)),
            "max_calibration_error": float(np.max(calibration_errors)),
            "n_samples": len(self.actuals),
        }


class DriftDetector:
    """Detect model performance degradation over time."""

    def __init__(self, baseline_auc: float = 0.75, alert_threshold: float = 0.05):
        """
        Args:
            baseline_auc: Expected AUC on validation set
            alert_threshold: Alert if AUC drops more than this fraction
        """
        self.baseline_auc = baseline_auc
        self.alert_threshold = alert_threshold
        self.recent_performance = ModelPerformanceMetrics(window_size=100)
        self.baseline_performance = ModelPerformanceMetrics(window_size=1000)

    def update(self, prediction: float, actual: Optional[int] = None) -> Optional[str]:
        """
        Update drift detector with a new prediction.

        Returns:
            Alert message if drift detected, else None
        """
        self.recent_performance.add(prediction, actual)
        self.baseline_performance.add(prediction, actual)

        if len(self.recent_performance.predictions) < 50:
            return None  # Need enough data

        recent_auc = self.recent_performance.compute_auc()
        if recent_auc is None:
            return None

        relative_drop = (self.baseline_auc - recent_auc) / self.baseline_auc
        if relative_drop > self.alert_threshold:
            msg = (
                f"Model drift detected: AUC dropped from {self.baseline_auc:.3f} to "
                f"{recent_auc:.3f} (−{relative_drop:.1%}). Recommend model retraining."
            )
            logger.warning(msg)
            return msg

        return None


class RiskThresholdController:
    """Generate patient safety alerts based on risk thresholds."""

    # Risk categories and thresholds
    THRESHOLDS = {
        "deterioration": {"low": 0.1, "moderate": 0.3, "high": 0.7},
        "sepsis": {"low": 0.15, "moderate": 0.35, "high": 0.65},
        "aki": {"low": 0.2, "moderate": 0.4, "high": 0.75},
        "cardiac": {"low": 0.25, "moderate": 0.5, "high": 0.8},
    }

    # Alert frequency cap (max alerts per patient per hour)
    ALERT_COOLDOWN_MINUTES = 60

    def __init__(self):
        self.last_alert_time: Dict[str, datetime] = {}

    def should_alert(self, patient_id: str) -> bool:
        """Check if patient is on cooldown from previous alerts."""
        if patient_id not in self.last_alert_time:
            return True
        elapsed = datetime.now() - self.last_alert_time[patient_id]
        return elapsed > timedelta(minutes=self.ALERT_COOLDOWN_MINUTES)

    def generate_alert(
        self,
        patient_id: str,
        alert_type: str,
        predicted_risk: float,
        key_findings: List[str],
    ) -> Optional[RiskAlert]:
        """Generate a patient alert if thresholds are exceeded.

        Args:
            patient_id: Patient identifier
            alert_type: "deterioration", "sepsis", "aki", "cardiac"
            predicted_risk: Risk score 0.0–1.0
            key_findings: Lab values/patterns that drove the score

        Returns:
            RiskAlert if threshold exceeded and not on cooldown, else None
        """
        if not self.should_alert(patient_id):
            return None

        thresholds = self.THRESHOLDS.get(alert_type, {"low": 0.1, "moderate": 0.3, "high": 0.7})

        if predicted_risk < thresholds["low"]:
            return None

        if predicted_risk >= thresholds["high"]:
            risk_level = "critical"
            recommendation = (
                f"URGENT: {alert_type.upper()} risk {predicted_risk:.0%}. "
                "Review labs immediately. Consider escalation."
            )
        elif predicted_risk >= thresholds["moderate"]:
            risk_level = "high"
            recommendation = f"High {alert_type} risk ({predicted_risk:.0%}). Monitor closely."
        else:
            risk_level = "moderate"
            recommendation = f"Moderate {alert_type} risk ({predicted_risk:.0%}). Note in chart."

        alert = RiskAlert(
            patient_id=patient_id,
            timestamp=datetime.now(),
            risk_level=risk_level,
            predicted_risk=predicted_risk,
            alert_type=alert_type,
            recommendation=recommendation,
            audit_trail=key_findings,
        )

        self.last_alert_time[patient_id] = datetime.now()
        return alert


class AnomalyDetector:
    """Detect labs that are unusual for a patient or population."""

    def __init__(self, population_stats: Optional[Dict[str, Tuple[float, float]]] = None):
        """
        Args:
            population_stats: {analyte: (mean, std)} for Z-score calculation
        """
        self.population_stats = population_stats or {}
        self.patient_baselines: Dict[str, Dict[str, float]] = {}

    def update_baseline(self, patient_id: str, labs: Dict[str, Optional[float]]) -> None:
        """Update running mean for a patient's lab values."""
        if patient_id not in self.patient_baselines:
            self.patient_baselines[patient_id] = {}

        baseline = self.patient_baselines[patient_id]
        for analyte, value in labs.items():
            if value is not None:
                if analyte not in baseline:
                    baseline[analyte] = value
                else:
                    # Exponential moving average (weight recent values)
                    baseline[analyte] = 0.9 * baseline[analyte] + 0.1 * value

    def detect_anomalies(
        self, patient_id: str, labs: Dict[str, Optional[float]]
    ) -> List[Tuple[str, float, str]]:
        """Detect values that deviate from patient baseline or population norms.

        Returns:
            List of (analyte, z_score, severity) tuples
        """
        anomalies = []
        baseline = self.patient_baselines.get(patient_id, {})

        for analyte, value in labs.items():
            if value is None:
                continue

            z_score = None
            if analyte in baseline:
                patient_mean = baseline[analyte]
                patient_std = max(abs(patient_mean * 0.1), 0.1)  # Rough estimate
                z_score = abs((value - patient_mean) / patient_std)
            elif analyte in self.population_stats:
                pop_mean, pop_std = self.population_stats[analyte]
                z_score = abs((value - pop_mean) / pop_std)

            if z_score and z_score > 2.0:
                severity = "marked" if z_score > 3.0 else "mild"
                anomalies.append((analyte, z_score, severity))

        return sorted(anomalies, key=lambda x: x[1], reverse=True)


class RealTimeMonitor:
    """Unified interface for all monitoring functions."""

    def __init__(self, baseline_model_auc: float = 0.75):
        self.drift_detector = DriftDetector(baseline_auc=baseline_model_auc)
        self.alert_controller = RiskThresholdController()
        self.anomaly_detector = AnomalyDetector()

    def process_prediction(
        self,
        patient_id: str,
        predicted_risk: float,
        alert_type: str = "deterioration",
        key_findings: Optional[List[str]] = None,
        actual_outcome: Optional[int] = None,
    ) -> Dict[str, Optional[RiskAlert | str]]:
        """Process a single prediction and generate alerts/drift warnings.

        Returns:
            {
                "risk_alert": RiskAlert or None,
                "drift_warning": str or None,
            }
        """
        key_findings = key_findings or []

        return {
            "risk_alert": self.alert_controller.generate_alert(
                patient_id, alert_type, predicted_risk, key_findings
            ),
            "drift_warning": self.drift_detector.update(predicted_risk, actual_outcome),
        }

    def process_labs(
        self,
        patient_id: str,
        labs: Dict[str, Optional[float]],
    ) -> Dict[str, Optional[List[Tuple[str, float, str]]]]:
        """Detect anomalies in lab panel relative to patient history."""
        self.anomaly_detector.update_baseline(patient_id, labs)
        return {
            "anomalies": self.anomaly_detector.detect_anomalies(patient_id, labs),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    monitor = RealTimeMonitor(baseline_model_auc=0.75)

    # Simulate a critical patient's predictions over time
    print("Monitoring simulation:")
    for i in range(10):
        risk = 0.3 + i * 0.08  # Gradually increasing risk
        actual = 1 if i > 6 else 0  # Deteriorates after 6 predictions

        result = monitor.process_prediction(
            patient_id="P001",
            predicted_risk=risk,
            alert_type="deterioration",
            key_findings=[f"Lab {i}: creatinine rising"],
            actual_outcome=actual,
        )

        if result["risk_alert"]:
            print(f"\n[Alert #{i}] {result['risk_alert'].recommendation}")

        if result["drift_warning"]:
            print(f"\n[Drift] {result['drift_warning']}")

    # Check calibration
    perf = monitor.drift_detector.recent_performance
    cal = perf.compute_calibration()
    if cal:
        print(f"\nCalibration: mean error = {cal['mean_calibration_error']:.3f}")
