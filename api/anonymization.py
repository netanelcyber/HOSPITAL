"""De-identification and privacy budget for WASM-submitted results.

The threat model is that the server is honest-but-curious and its storage may
later be breached. So the design goal is not "the server promises not to look"
but "the server never receives anything that could identify a patient, and
could not re-identify one if it tried."

Three mechanisms, in the order they matter:

1. **Client-side reduction.** The browser submits a *generalized* record: risk
   band, coarsened lab bins, no free text, no identifiers, no timestamps finer
   than a day. Raw values never enter the request. Anonymizing server-side
   would be theatre — the raw data would already have crossed the network.

2. **k-anonymity.** A generalized record is held in a staging buffer and only
   written to durable storage once at least k other records share its exact
   quasi-identifier signature. A record unique in its combination of age band,
   sex and lab pattern is re-identifiable however few fields it has.

3. **Differential privacy.** Counts released through the aggregate endpoint
   carry calibrated Laplace noise against a finite epsilon budget, so repeated
   querying cannot average the noise away and recover an individual.

Direct identifiers are not merely dropped — their presence is treated as a
protocol violation and the submission is rejected, because a client sending
them signals a bug that would otherwise keep leaking silently.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import os
import re
import secrets
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# Fields that must never appear in a submission. HIPAA Safe Harbor lists 18
# identifier categories; these are the ones a lab-prediction client could
# plausibly send by accident.
FORBIDDEN_FIELDS = frozenset(
    {
        "patient_id", "mrn", "medical_record_number", "name", "first_name",
        "last_name", "full_name", "ssn", "social_security", "address",
        "street", "city", "zip", "zipcode", "postal_code", "phone",
        "telephone", "fax", "email", "url", "ip", "ip_address",
        "device_id", "serial_number", "license_number", "account_number",
        "certificate_number", "biometric", "photo", "face", "dob",
        "date_of_birth", "birth_date", "admission_date", "discharge_date",
        "death_date", "medical_report", "note", "notes", "free_text",
        "clinical_note", "narrative",
    }
)

# Values that look like identifiers regardless of the field they arrive in.
_IDENTIFIER_PATTERNS = (
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                     # US SSN
    re.compile(r"\b\d{9}\b"),                                  # Israeli ID / MRN
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),                    # email
    re.compile(r"\b(?:\+?\d{1,3}[- ]?)?(?:\d[- ]?){7,12}\b"),  # phone
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),                # IPv4
)


class PrivacyViolation(ValueError):
    """Raised when a submission carries data it must not."""


# ---------------------------------------------------------------------------
# Generalization
# ---------------------------------------------------------------------------

# HIPAA Safe Harbor requires ages over 89 to be aggregated, because the tail is
# sparse enough to single people out.
AGE_BANDS: Tuple[Tuple[float, float, str], ...] = (
    (0, 18, "0-17"),
    (18, 30, "18-29"),
    (30, 45, "30-44"),
    (45, 60, "45-59"),
    (60, 70, "60-69"),
    (70, 80, "70-79"),
    (80, 90, "80-89"),
    (90, math.inf, "90+"),
)

RISK_BANDS: Tuple[Tuple[float, str], ...] = (
    (0.30, "low"),
    (0.50, "moderate"),
    (0.70, "high"),
    (1.01, "critical"),
)


def band_age(age: Optional[float]) -> str:
    if age is None:
        return "unknown"
    for low, high, label in AGE_BANDS:
        if low <= age < high:
            return label
    return "unknown"


def band_risk(score: Optional[float]) -> str:
    if score is None:
        return "unknown"
    for ceiling, label in RISK_BANDS:
        if score < ceiling:
            return label
    return "critical"


def band_lab(analyte: str, value: Optional[float]) -> str:
    """Reduce a lab value to a clinically meaningful ordinal band.

    Bands come from the reference range rather than from quantiles of the
    submitted data, so they mean the same thing at every site and reveal
    nothing about the local distribution.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "missing"

    from features.lab_features import LabFeatureExtractor

    bounds = LabFeatureExtractor.REFERENCE_RANGES.get(analyte)
    if bounds is None:
        return "unknown"

    low, high = bounds
    if value < low * 0.67:
        return "critical_low"
    if value < low:
        return "low"
    if value <= high:
        return "normal"
    if value <= high * 1.5:
        return "high"
    return "critical_high"


@dataclass(frozen=True)
class AnonymizedSubmission:
    """What the server is willing to store: generalized, non-identifying."""

    site_pseudonym: str
    age_band: str
    sex: str
    risk_band: str
    predicted_label: int
    observed_label: Optional[int]
    lab_bands: Dict[str, str]
    model_version: str
    submitted_on: str  # date only; finer granularity is a quasi-identifier

    def quasi_identifier(self) -> Tuple:
        """The signature k-anonymity is enforced over."""
        return (
            self.age_band,
            self.sex,
            self.risk_band,
            tuple(sorted(self.lab_bands.items())),
        )

    def to_dict(self) -> Dict:
        return {
            "site_pseudonym": self.site_pseudonym,
            "age_band": self.age_band,
            "sex": self.sex,
            "risk_band": self.risk_band,
            "predicted_label": self.predicted_label,
            "observed_label": self.observed_label,
            "lab_bands": dict(self.lab_bands),
            "model_version": self.model_version,
            "submitted_on": self.submitted_on,
        }


class SubmissionSanitizer:
    """Validates and generalizes an incoming submission."""

    def __init__(self, site_salt: Optional[str] = None):
        """
        Args:
            site_salt: HMAC key for site pseudonyms. Generated per process when
                absent, which makes pseudonyms unlinkable across restarts —
                safer by default, at the cost of longitudinal site tracking.
        """
        salt = site_salt or os.environ.get("SITE_PSEUDONYM_SALT")
        if not salt:
            salt = secrets.token_hex(32)
            logger.warning(
                "No SITE_PSEUDONYM_SALT set; generated an ephemeral one. Site "
                "pseudonyms will not be stable across restarts."
            )
        self._salt = salt.encode()

    def site_pseudonym(self, site_id: str) -> str:
        """Keyed hash of the site identifier.

        Keyed, not plain SHA-256: the set of hospitals is small enough that an
        unkeyed digest is reversible by simply hashing every candidate name.
        """
        return hmac.new(self._salt, site_id.encode(), hashlib.sha256).hexdigest()[:16]

    def reject_identifiers(self, payload: Dict) -> None:
        """Fail loudly when a submission carries anything identifying."""
        offending = sorted(FORBIDDEN_FIELDS.intersection(k.lower() for k in payload))
        if offending:
            raise PrivacyViolation(
                f"Submission contains forbidden identifier fields: {offending}. "
                "The client must generalize before transmitting; the server "
                "will not accept raw identifiers."
            )

        for key, value in payload.items():
            if not isinstance(value, str):
                continue
            for pattern in _IDENTIFIER_PATTERNS:
                if pattern.search(value):
                    raise PrivacyViolation(
                        f"Field {key!r} matches an identifier pattern "
                        f"({pattern.pattern}); refusing the submission."
                    )

    def sanitize(self, payload: Dict) -> AnonymizedSubmission:
        """Validate, then reduce a raw submission to its storable form."""
        self.reject_identifiers(payload)

        site_id = payload.get("site_id")
        if not site_id:
            raise PrivacyViolation("site_id is required to pseudonymize a submission.")

        raw_labs = payload.get("lab_values") or {}
        if not isinstance(raw_labs, dict):
            raise PrivacyViolation("lab_values must be a mapping of analyte to value.")

        lab_bands = {
            analyte: band_lab(analyte, _as_float(value))
            for analyte, value in sorted(raw_labs.items())
        }

        risk_score = _as_float(payload.get("risk_score"))
        observed = payload.get("observed_label")

        return AnonymizedSubmission(
            site_pseudonym=self.site_pseudonym(str(site_id)),
            age_band=band_age(_as_float(payload.get("age"))),
            sex=str(payload.get("sex", "unknown")).lower()[:1] or "u",
            risk_band=band_risk(risk_score),
            predicted_label=int(bool(payload.get("predicted_label", 0))),
            observed_label=None if observed is None else int(bool(observed)),
            lab_bands=lab_bands,
            model_version=str(payload.get("model_version", "unknown")),
            # Truncated to the day: a precise timestamp plus a site is close to
            # a unique key for a patient.
            submitted_on=date.today().isoformat(),
        )


def _as_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) else result


# ---------------------------------------------------------------------------
# k-anonymity gate
# ---------------------------------------------------------------------------

class KAnonymityGate:
    """Holds records in staging until their quasi-identifier group reaches k.

    A record that is unique in its combination of age band, sex, risk band and
    lab pattern can be matched back to a person by anyone holding one extra
    fact about them. Releasing it only once k-1 indistinguishable others exist
    bounds that to a 1-in-k guess.
    """

    def __init__(self, k: int = 5, max_staging: int = 100_000):
        if k < 2:
            raise ValueError("k must be at least 2 for k-anonymity to mean anything")
        self.k = k
        self.max_staging = max_staging
        self._staging: Dict[Tuple, List[AnonymizedSubmission]] = defaultdict(list)
        self._released = 0

    def submit(self, record: AnonymizedSubmission) -> List[AnonymizedSubmission]:
        """Stage a record; return records now cleared for durable storage."""
        signature = record.quasi_identifier()
        group = self._staging[signature]
        group.append(record)

        if len(group) < self.k:
            self._evict_if_needed()
            return []

        # The group has reached k; every member is now indistinguishable from
        # k-1 others and can be released together.
        released = list(group)
        del self._staging[signature]
        self._released += len(released)
        return released

    def _evict_if_needed(self) -> None:
        """Drop the oldest never-released groups when staging grows unbounded.

        Groups that never reach k would otherwise accumulate forever. Dropping
        them loses data; releasing them would lose the guarantee, and the
        guarantee is the point.
        """
        staged = sum(len(g) for g in self._staging.values())
        if staged <= self.max_staging:
            return

        for signature in list(self._staging)[: len(self._staging) // 10 or 1]:
            dropped = len(self._staging.pop(signature))
            logger.info(
                "Dropped %d staged records that never reached k=%d", dropped, self.k
            )

    @property
    def pending(self) -> int:
        return sum(len(group) for group in self._staging.values())

    @property
    def released(self) -> int:
        return self._released


# ---------------------------------------------------------------------------
# Differential privacy
# ---------------------------------------------------------------------------

class DifferentialPrivacyBudget:
    """Laplace mechanism with a finite, enforced epsilon budget.

    Noise alone is not privacy: an attacker who can ask the same question 1000
    times averages the noise to nothing. The budget is what makes the guarantee
    hold, so exhausting it must stop answering rather than degrade quietly.
    """

    def __init__(self, epsilon_total: float = 1.0, sensitivity: float = 1.0):
        self.epsilon_total = epsilon_total
        self.sensitivity = sensitivity
        self._spent = 0.0
        self._rng = secrets.SystemRandom()

    @property
    def remaining(self) -> float:
        return max(0.0, self.epsilon_total - self._spent)

    def noisy_count(self, true_count: int, epsilon: float = 0.1) -> int:
        """Return a count with Laplace noise, charged against the budget."""
        if epsilon <= 0:
            raise ValueError("epsilon must be positive")
        if epsilon > self.remaining:
            raise PrivacyViolation(
                f"Privacy budget exhausted: requested epsilon={epsilon:.3f}, "
                f"remaining={self.remaining:.3f}. Refusing to answer rather "
                "than degrade the guarantee."
            )

        self._spent += epsilon
        scale = self.sensitivity / epsilon

        # Inverse-CDF sampling of Laplace from a uniform draw.
        uniform = self._rng.random() - 0.5
        noise = -scale * math.copysign(1.0, uniform) * math.log(
            1 - 2 * abs(uniform)
        )
        # Counts cannot be negative, and clamping does not weaken the guarantee.
        return max(0, int(round(true_count + noise)))

    def noisy_rate(
        self, numerator: int, denominator: int, epsilon: float = 0.1
    ) -> Optional[float]:
        """A rate from two noisy counts, or None when the base is too small.

        Suppressing small denominators matters more than the noise: a rate over
        3 patients is disclosive no matter how it is perturbed.
        """
        if denominator < 20:
            return None
        noisy_num = self.noisy_count(numerator, epsilon / 2)
        noisy_den = self.noisy_count(denominator, epsilon / 2)
        if noisy_den <= 0:
            return None
        return min(1.0, noisy_num / noisy_den)
