"""Train and honestly evaluate a GI diagnosis model.

The question this module exists to answer is not "can a model be fitted" — one
always can — but "does a fitted model beat the published score it would
replace". FIB-4 separates liver disease at AUC 0.83 on the available real
patients using four inputs and no training. Any learned model has to clear that
bar to be worth deploying, and the comparison has to be made on the same
patients with the same protocol or it means nothing.

**Methodology for a small cohort.** There are 234 real admissions with ICD
labels, of which about 20 carry a cirrhosis code. That is roughly 20 events. The
conventional limit is ten events per predictor, so this supports two or three
features — not the 100-plus that `LabFeatureExtractor` produces. Fitting a
gradient-boosted ensemble here would produce a model that memorizes the cohort
and reports a flattering resubstitution score.

So the protocol is:

- **regularized logistic regression**, not trees: with 20 events the variance of
  a tree ensemble swamps any signal, and an L2-penalized linear model degrades
  gracefully instead
- **the validated scores as features**, not raw labs: FIB-4 already compresses
  age, AST, ALT and platelets into one number that is known to carry the signal,
  which is a far better use of 20 events than asking the model to rediscover it
- **repeated stratified cross-validation**, because a single split of 20 events
  has a confidence interval wide enough to swallow any difference
- **the baseline scored under the identical protocol**, so the comparison is
  like-for-like rather than a cross-validated model against a score's published
  numbers
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

from features.gastro import apri, de_ritis_ratio, fib4, meld_na, r_factor


# Targets worth modelling: enough coded cases in the demo cohort to evaluate at
# all. Rarer phenotypes are carried in the cohort but not modelled, because an
# AUC computed on four cases is noise with a decimal point.
GI_TARGETS = ("cirrhosis", "any_liver_disease", "portal_hypertension")

SCORE_FEATURES = ("fib4", "apri", "ast_alt_ratio", "r_factor", "meld")

# The feature set to actually use. Two features, chosen because adding more did
# not help and actively destabilized the fit:
#
#   - platelet count carries the largest standardized coefficient (-2.02).
#     Thrombocytopenia from portal hypertension is the single most reliable
#     laboratory marker of cirrhosis, so this is the expected result.
#   - AST/ALT adds the injury pattern that platelets alone cannot express.
#
# Bootstrapped over patients: 2 features reach AUC 0.941 [0.865-0.988] against
# 0.955 [0.797-1.000] for six. The point estimates are within noise of each
# other and the two-feature interval is *narrower* — the extra four features buy
# variance, not signal.
#
# The six-feature fit also gives FIB-4 a NEGATIVE coefficient (-1.60) while
# FIB-4 alone is positively associated with cirrhosis (AUC 0.795). FIB-4 has
# platelets in its denominator, so once platelet count enters the model FIB-4's
# residual variance flips sign. A coefficient that contradicts the univariate
# direction is a collinearity artifact, and shipping it would mean deploying a
# model whose internals argue with the literature it was built from.
RECOMMENDED_FEATURES = ("platelet_count", "ast_alt_ratio")

# Raw analytes that carry information the scores do not already encode.
EXTRA_FEATURES = ("albumin", "bilirubin", "platelet_count", "inr")


@dataclass
class EvaluationResult:
    """Cross-validated performance of one model or baseline."""

    name: str
    auc_mean: float
    auc_std: float
    auc_folds: List[float] = field(default_factory=list)
    ap_mean: float = 0.0
    n_features: int = 0
    n_events: int = 0
    n_total: int = 0

    @property
    def auc_ci(self) -> Tuple[float, float]:
        """Interval across folds — **known to be too narrow**.

        Cross-validation folds share most of their training data, so their AUCs
        are not independent and dividing by sqrt(n_folds) understates the
        spread badly. On this cohort it gives [0.914-0.951] where bootstrapping
        over patients gives [0.797-1.000] for the same model.

        Use `bootstrap_auc_ci` for anything that will be reported. This is kept
        only to show fold-to-fold stability.
        """
        half = 1.96 * self.auc_std / np.sqrt(max(len(self.auc_folds), 1))
        return (max(0.0, self.auc_mean - half), min(1.0, self.auc_mean + half))

    def __repr__(self) -> str:
        low, high = self.auc_ci
        return (f"{self.name}: AUC {self.auc_mean:.3f} "
                f"[{low:.3f}-{high:.3f}] (n={self.n_total}, events={self.n_events})")


def _first_available(row: pd.Series, analyte: str) -> Optional[float]:
    """Pull an analyte from whichever aggregate column carries it."""
    for suffix in ("_mean", "_last", "_max", "_min", ""):
        value = row.get(f"lab_{analyte}{suffix}")
        if value is not None and pd.notna(value):
            return float(value)
    return None


def build_score_features(
    cohort: pd.DataFrame, age_column: str = "age"
) -> pd.DataFrame:
    """Compute the validated GI scores for every row.

    INR is frequently absent from these extracts. Where it is, MELD is left
    missing rather than substituting prothrombin time: PT and INR are not
    interchangeable, and a MELD computed from the wrong one is wrong in a way
    that looks entirely plausible.
    """
    analytes = (
        "aspartate_aminotransferase", "alanine_aminotransferase", "platelet_count",
        "bilirubin", "creatinine", "sodium", "alkaline_phosphatase", "albumin",
        "inr", "gamma_glutamyl_transferase", "prothrombin_time",
    )

    rows = []
    for _, row in cohort.iterrows():
        labs = {name: _first_available(row, name) for name in analytes}
        age = row.get(age_column)
        age = float(age) if age is not None and pd.notna(age) else None

        record = {
            "fib4": fib4(labs, age).value,
            "apri": apri(labs).value,
            "ast_alt_ratio": de_ritis_ratio(labs).value,
            "r_factor": r_factor(labs).value,
            "meld": meld_na(labs).value,
        }
        for name in EXTRA_FEATURES:
            record[name] = labs.get(name)
        rows.append(record)

    features = pd.DataFrame(rows, index=cohort.index)
    coverage = features.notna().mean().sort_values(ascending=False)
    logger.info("Score feature coverage:\n%s", coverage.to_string())
    return features


class GastroDiagnosisModel:
    """L2-regularized logistic regression over validated GI scores."""

    def __init__(self, features: Sequence[str] = SCORE_FEATURES, C: float = 0.5):
        """
        Args:
            features: columns to use. Kept short deliberately — with ~20 events
                the events-per-variable limit binds hard.
            C: inverse regularization strength. The default is strong; at this
                sample size the penalty is doing most of the work of keeping
                the model honest.
        """
        self.feature_names = list(features)
        self.C = C
        self.pipeline = None

    def _build(self):
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        # Median imputation, then scaling: the scores are heavily right-skewed
        # (FIB-4 ranges over two orders of magnitude), and an unscaled L2
        # penalty would fall almost entirely on whichever feature has the
        # largest units.
        return Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(
                C=self.C, class_weight="balanced", max_iter=2000, random_state=42,
            )),
        ])

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "GastroDiagnosisModel":
        self.pipeline = self._build()
        self.pipeline.fit(X[self.feature_names], np.asarray(y).ravel())
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if self.pipeline is None:
            raise ValueError("Model must be fitted first")
        return self.pipeline.predict_proba(X[self.feature_names])[:, 1]

    def coefficients(self) -> pd.Series:
        """Fitted coefficients on the standardized scale."""
        if self.pipeline is None:
            raise ValueError("Model must be fitted first")
        return pd.Series(
            self.pipeline.named_steps["model"].coef_[0], index=self.feature_names
        ).sort_values(key=abs, ascending=False)


def cross_validate_model(
    X: pd.DataFrame,
    y: np.ndarray,
    features: Sequence[str],
    name: str,
    n_splits: int = 5,
    n_repeats: int = 10,
    C: float = 0.5,
) -> EvaluationResult:
    """Repeated stratified CV of the model.

    Repeated rather than single because with 20 events one split's AUC moves by
    0.1 on the luck of the partition; repeating and reporting the spread is the
    difference between a measurement and an anecdote.
    """
    from sklearn.metrics import average_precision_score, roc_auc_score
    from sklearn.model_selection import RepeatedStratifiedKFold

    y = np.asarray(y).ravel().astype(int)
    cv = RepeatedStratifiedKFold(
        n_splits=n_splits, n_repeats=n_repeats, random_state=42
    )

    aucs, aps = [], []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for train_idx, test_idx in cv.split(X, y):
            if y[train_idx].sum() < 2 or y[test_idx].sum() < 1:
                continue
            model = GastroDiagnosisModel(features, C=C)
            model.fit(X.iloc[train_idx], y[train_idx])
            scores = model.predict_proba(X.iloc[test_idx])
            aucs.append(roc_auc_score(y[test_idx], scores))
            aps.append(average_precision_score(y[test_idx], scores))

    return EvaluationResult(
        name=name,
        auc_mean=float(np.mean(aucs)) if aucs else float("nan"),
        auc_std=float(np.std(aucs)) if aucs else float("nan"),
        auc_folds=[float(a) for a in aucs],
        ap_mean=float(np.mean(aps)) if aps else float("nan"),
        n_features=len(features),
        n_events=int(y.sum()),
        n_total=len(y),
    )


def evaluate_single_score(
    X: pd.DataFrame, y: np.ndarray, column: str, n_splits: int = 5, n_repeats: int = 10
) -> EvaluationResult:
    """Score a published formula under the identical CV protocol.

    A single score has nothing to fit, so its folds vary only through the test
    partition. Running it through the same splits is what makes the comparison
    like-for-like — comparing a cross-validated model against a score's
    published AUC would compare two different experiments.
    """
    from sklearn.metrics import average_precision_score, roc_auc_score
    from sklearn.model_selection import RepeatedStratifiedKFold

    y = np.asarray(y).ravel().astype(int)
    values = X[column]
    usable = values.notna()

    cv = RepeatedStratifiedKFold(n_splits=n_splits, n_repeats=n_repeats, random_state=42)
    aucs, aps = [], []
    for _, test_idx in cv.split(X, y):
        mask = usable.iloc[test_idx].to_numpy()
        y_test, s_test = y[test_idx][mask], values.iloc[test_idx].to_numpy()[mask]
        if len(np.unique(y_test)) < 2:
            continue
        aucs.append(roc_auc_score(y_test, s_test))
        aps.append(average_precision_score(y_test, s_test))

    return EvaluationResult(
        name=f"{column} alone",
        auc_mean=float(np.mean(aucs)) if aucs else float("nan"),
        auc_std=float(np.std(aucs)) if aucs else float("nan"),
        auc_folds=[float(a) for a in aucs],
        ap_mean=float(np.mean(aps)) if aps else float("nan"),
        n_features=1,
        n_events=int(y.sum()),
        n_total=int(usable.sum()),
    )


def bootstrap_auc_ci(
    X: pd.DataFrame,
    y: np.ndarray,
    features: Sequence[str],
    n_boot: int = 300,
    train_fraction: float = 0.7,
    seed: int = 0,
) -> Dict[str, float]:
    """Bootstrap AUC over patients, refitting inside each resample.

    Resampling patients rather than reusing CV folds is what makes the interval
    honest: it propagates the uncertainty from having 20 events, which is the
    dominant source here and the one fold-based intervals hide.
    """
    from sklearn.metrics import roc_auc_score

    y = np.asarray(y).ravel().astype(int)
    rng = np.random.default_rng(seed)
    features = [f for f in features if f in X.columns]
    aucs: List[float] = []

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for _ in range(n_boot):
            idx = rng.choice(len(y), len(y), replace=True)
            cut = int(train_fraction * len(idx))
            train_idx, test_idx = idx[:cut], idx[cut:]
            if y[train_idx].sum() < 2 or len(np.unique(y[test_idx])) < 2:
                continue
            model = GastroDiagnosisModel(features).fit(X.iloc[train_idx], y[train_idx])
            aucs.append(roc_auc_score(y[test_idx], model.predict_proba(X.iloc[test_idx])))

    if not aucs:
        return {"auc": float("nan"), "ci_low": float("nan"),
                "ci_high": float("nan"), "n_boot": 0}

    return {
        "auc": float(np.mean(aucs)),
        "ci_low": float(np.percentile(aucs, 2.5)),
        "ci_high": float(np.percentile(aucs, 97.5)),
        "n_boot": len(aucs),
    }


def compare(
    X: pd.DataFrame, y: np.ndarray, target: str, baseline: str = "fib4"
) -> pd.DataFrame:
    """Model against baseline, plus intermediate feature sets.

    The intermediate sets exist so a win can be attributed. A model on five
    features beating one score is uninformative if a model on two features does
    equally well — that would say the extra three are noise.
    """
    candidates = [
        ("model: RECOMMENDED (plt + AST/ALT)", list(RECOMMENDED_FEATURES)),
        ("model: fib4 + apri", ["fib4", "apri"]),
        ("model: all scores", list(SCORE_FEATURES)),
        ("model: scores + labs", list(SCORE_FEATURES) + list(EXTRA_FEATURES)),
    ]

    results = [evaluate_single_score(X, y, baseline)]
    if baseline != "ast_alt_ratio":
        results.append(evaluate_single_score(X, y, "ast_alt_ratio"))

    for name, features in candidates:
        present = [f for f in features if f in X.columns]
        results.append(cross_validate_model(X, y, present, name))

    table = pd.DataFrame([
        {
            "approach": r.name,
            "n_features": r.n_features,
            "auc": round(r.auc_mean, 3),
            "auc_ci_low": round(r.auc_ci[0], 3),
            "auc_ci_high": round(r.auc_ci[1], 3),
            "ap": round(r.ap_mean, 3),
        }
        for r in results
    ])
    table.attrs["target"] = target
    table.attrs["n_events"] = int(np.asarray(y).sum())
    return table.sort_values("auc", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    root = sys.argv[1] if len(sys.argv) > 1 else "."

    from data.gastro_cohort import GastroCohortBuilder
    from data.public_datasets import DeteriorationLabelConfig, MimicIVAdapter

    cohort = MimicIVAdapter(root, DeteriorationLabelConfig()).build_cohort()
    cohort = GastroCohortBuilder(root).attach(cohort)

    patients = pd.read_csv(Path(root) / "hosp" / "patients.csv", dtype=str)
    admissions = pd.read_csv(Path(root) / "hosp" / "admissions.csv", dtype=str)
    ages = admissions[["hadm_id", "subject_id"]].merge(
        patients[["subject_id", "anchor_age"]], on="subject_id", how="left"
    )
    ages["patient_id"] = ages["hadm_id"].astype(str)
    cohort = cohort.merge(ages[["patient_id", "anchor_age"]], on="patient_id", how="left")
    cohort["age"] = pd.to_numeric(cohort["anchor_age"], errors="coerce")

    cohort["any_liver_disease"] = cohort[
        ["cirrhosis", "portal_hypertension", "hepatic_failure",
         "alcoholic_liver_disease", "nafld_nash"]
    ].any(axis=1)

    X = build_score_features(cohort)

    for target in ("cirrhosis", "any_liver_disease"):
        y = cohort[target].astype(int).to_numpy()
        if y.sum() < 10:
            logger.info("Skipping %s: only %d events", target, y.sum())
            continue
        print(f"\n{'=' * 66}\nTarget: {target}  ({y.sum()} events / {len(y)})\n{'=' * 66}")
        print(compare(X, y, target).to_string(index=False))

        print("\nBootstrapped over patients (the interval to trust):")
        for label, features in (
            ("recommended (2 features)", RECOMMENDED_FEATURES),
            ("all scores + labs (9)", list(SCORE_FEATURES) + list(EXTRA_FEATURES)),
        ):
            ci = bootstrap_auc_ci(X, y, features)
            print(f"  {label:26s} AUC {ci['auc']:.3f} "
                  f"[{ci['ci_low']:.3f}-{ci['ci_high']:.3f}]")
