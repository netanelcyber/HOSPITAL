"""Lab test feature extraction and engineering."""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
import logging
from sklearn.preprocessing import StandardScaler, MinMaxScaler

logger = logging.getLogger(__name__)


class LabFeatureExtractor:
    """Extracts and engineers features from laboratory tests."""

    # Reference ranges for lab tests (normal values)
    REFERENCE_RANGES = {
        # Core metabolic panel
        "glucose": (70, 100),  # mg/dL fasting
        "sodium": (135, 145),  # mmol/L
        "potassium": (3.5, 5.0),  # mmol/L
        "chloride": (98, 107),  # mmol/L
        "bicarbonate": (23, 29),  # mmol/L
        "blood_urea_nitrogen": (7, 20),  # mg/dL
        "creatinine": (0.7, 1.3),  # mg/dL
        "calcium": (8.5, 10.2),  # mg/dL
        "magnesium": (1.7, 2.2),  # mg/dL
        "phosphate": (2.5, 4.5),  # mg/dL

        # Liver function
        "alanine_aminotransferase": (7, 56),  # U/L
        "aspartate_aminotransferase": (10, 40),  # U/L
        "alkaline_phosphatase": (44, 147),  # U/L
        "bilirubin": (0.1, 1.2),  # mg/dL
        "albumin": (3.5, 5.0),  # g/dL
        "total_protein": (6.0, 8.3),  # g/dL

        # Coagulation
        "prothrombin_time": (11, 13.5),  # seconds
        "partial_thromboplastin_time": (25, 35),  # seconds
        "inr": (0.8, 1.1),  # ratio

        # Hematology
        "platelet_count": (150, 400),  # K/uL
        "white_blood_cell_count": (4.5, 11.0),  # K/uL
        "red_blood_cell_count": (4.5, 5.9),  # M/uL
        "hemoglobin": (12.0, 17.5),  # g/dL
        "hematocrit": (41, 53),  # %
        "mean_corpuscular_volume": (80, 100),  # fL

        # Cardiac markers
        "troponin_i": (0.0, 0.04),  # ng/mL
        "troponin_t": (0.0, 0.04),  # ng/mL
        "bnp": (0, 100),  # pg/mL (BNP)
        "nt_probnp": (0, 125),  # pg/mL (NT-proBNP)

        # Hemolysis & muscle injury
        "lactate_dehydrogenase": (140, 280),  # U/L
        "creatine_kinase": (30, 200),  # U/L
        "myoglobin": (0, 100),  # ng/mL

        # Pancreatic
        "amylase": (30, 110),  # U/L
        "lipase": (0, 60),  # U/L

        # Inflammatory markers
        "c_reactive_protein": (0, 10),  # mg/L
        "procalcitonin": (0, 0.5),  # ng/mL

        # Coagulation & thrombosis
        "d_dimer": (0, 0.5),  # μg/mL
        "fibrinogen": (200, 400),  # mg/dL

        # Thyroid
        "tsh": (0.4, 4.0),  # mIU/L
        "free_t4": (0.8, 1.8),  # ng/dL

        # Acids & gases (surrogate from metabolic panel)
        "ph": (7.35, 7.45),  # pH units
        "pco2": (35, 45),  # mmHg
        "po2": (80, 100),  # mmHg
    }

    def __init__(
        self,
        normalization: str = "z_score",
        handle_missing: str = "mean",
    ):
        """Initialize lab feature extractor.

        Args:
            normalization: 'z_score' or 'minmax'
            handle_missing: 'mean', 'forward_fill', or 'drop'
        """
        self.normalization = normalization
        self.handle_missing = handle_missing
        self.scaler = None
        self.feature_means = {}
        self.feature_columns: List[str] = []
        self.fitted = False

    def fit(self, df: pd.DataFrame) -> "LabFeatureExtractor":
        """Fit the feature extractor on training data.

        Args:
            df: DataFrame with lab test columns

        Returns:
            self
        """
        lab_cols = self._get_lab_columns(df)
        # Column order is part of the fitted scaler's contract and is replayed
        # verbatim by the WASM bundle, so it is recorded rather than re-derived.
        self.feature_columns = lab_cols

        # Handle missing values
        df_clean = df[lab_cols].copy()
        if self.handle_missing == "mean":
            self.feature_means = df_clean.mean().to_dict()
            df_clean = df_clean.fillna(self.feature_means)

        # Fit scaler
        if self.normalization == "z_score":
            self.scaler = StandardScaler()
        else:  # minmax
            self.scaler = MinMaxScaler()

        self.scaler.fit(df_clean)
        self.fitted = True
        logger.info("Lab feature extractor fitted")
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform lab test features.

        Args:
            df: DataFrame with lab test columns

        Returns:
            DataFrame with transformed features
        """
        if not self.fitted:
            raise ValueError("Feature extractor must be fitted first")

        lab_cols = self.feature_columns
        df_result = df.copy()

        missing = [c for c in lab_cols if c not in df.columns]
        if missing:
            raise ValueError(
                f"Columns seen during fit are absent at transform time: {missing}. "
                "The scaler's constants are positional, so a differing column "
                "set would scale the wrong features."
            )

        # Handle missing values
        df_clean = df[lab_cols].copy()
        if self.handle_missing == "mean":
            df_clean = df_clean.fillna(self.feature_means)

        # Engineered features are derived BEFORE scaling. They compare each
        # value against its clinical reference range in real units, so a
        # z-scored input would be measuring a standard deviation against mg/dL
        # and mean nothing.
        df_result = self._add_engineered_features(df_result, lab_cols)

        scaled_values = self.scaler.transform(df_clean)
        for i, col in enumerate(lab_cols):
            df_result[col] = scaled_values[:, i]

        return df_result

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fit and transform in one step.

        Args:
            df: DataFrame with lab test columns

        Returns:
            DataFrame with transformed features
        """
        return self.fit(df).transform(df)

    def _get_lab_columns(self, df: pd.DataFrame) -> List[str]:
        """Get all lab test columns from DataFrame."""
        lab_cols = [col for col in df.columns if col.startswith("lab_")]
        if not lab_cols:
            raise ValueError("No lab columns found (expected columns starting with 'lab_')")
        return lab_cols

    def _add_engineered_features(
        self, df: pd.DataFrame, lab_cols: List[str]
    ) -> pd.DataFrame:
        """Add engineered features from lab tests.

        Args:
            df: DataFrame with lab tests
            lab_cols: List of lab column names

        Returns:
            DataFrame with additional engineered features
        """
        df_result = df.copy()

        # 1. Deviation from normal (Z-score based on normal ranges)
        for col in lab_cols:
            test_name = col.replace("lab_", "")
            if test_name in self.REFERENCE_RANGES:
                low, high = self.REFERENCE_RANGES[test_name]
                normal_mid = (low + high) / 2
                normal_range = (high - low) / 2

                # Z-score relative to normal range
                df_result[f"{col}_abnormality"] = np.abs(
                    (df[col] - normal_mid) / normal_range
                )

        # 2. Critical flag (values outside 1.5x normal range)
        for col in lab_cols:
            test_name = col.replace("lab_", "")
            if test_name in self.REFERENCE_RANGES:
                low, high = self.REFERENCE_RANGES[test_name]
                df_result[f"{col}_critical"] = (
                    (df[col] < low * 0.67) | (df[col] > high * 1.5)
                ).astype(int)

        # 3. Kidney function (creatinine + BUN)
        if "lab_creatinine" in df_result.columns and "lab_blood_urea_nitrogen" in df_result.columns:
            df_result["kidney_risk"] = (
                df_result["lab_creatinine_abnormality"] * 0.5
                + df_result["lab_blood_urea_nitrogen_abnormality"] * 0.5
            )

        # 4. Liver function (AST + ALT + bilirubin)
        liver_cols = []
        if "lab_aspartate_aminotransferase" in df_result.columns:
            liver_cols.append("lab_aspartate_aminotransferase_abnormality")
        if "lab_alanine_aminotransferase" in df_result.columns:
            liver_cols.append("lab_alanine_aminotransferase_abnormality")
        if "lab_bilirubin" in df_result.columns:
            liver_cols.append("lab_bilirubin_abnormality")

        if liver_cols:
            df_result["liver_risk"] = df_result[liver_cols].mean(axis=1)

        # 5. Coagulation risk (PT + PTT + platelet count)
        coag_cols = []
        if "lab_prothrombin_time" in df_result.columns:
            coag_cols.append("lab_prothrombin_time_abnormality")
        if "lab_partial_thromboplastin_time" in df_result.columns:
            coag_cols.append("lab_partial_thromboplastin_time_abnormality")
        if "lab_platelet_count" in df_result.columns:
            coag_cols.append("lab_platelet_count_abnormality")

        if coag_cols:
            df_result["coagulation_risk"] = df_result[coag_cols].mean(axis=1)

        # 6. Electrolyte imbalance (sodium + potassium)
        if "lab_sodium" in df_result.columns and "lab_potassium" in df_result.columns:
            df_result["electrolyte_risk"] = (
                df_result["lab_sodium_abnormality"] * 0.5
                + df_result["lab_potassium_abnormality"] * 0.5
            )

        # 7. Total abnormality count
        abnormality_cols = [col for col in df_result.columns if "_abnormality" in col]
        if abnormality_cols:
            df_result["total_abnormality_count"] = (
                df_result[abnormality_cols] > 1.0
            ).sum(axis=1)

        # 8. Critical count
        critical_cols = [col for col in df_result.columns if "_critical" in col]
        if critical_cols:
            df_result["total_critical_count"] = df_result[critical_cols].sum(axis=1)

        logger.info(f"Added {len(df_result.columns) - len(lab_cols)} engineered features")
        return df_result

    def get_feature_importance_order(self) -> List[Tuple[str, float]]:
        """Get features in order of importance (variance based).

        Returns:
            List of (feature_name, importance_score) tuples
        """
        if self.scaler is None:
            raise ValueError("Feature extractor must be fitted first")

        if self.normalization == "z_score":
            variances = self.scaler.var_
        else:
            variances = np.var(self.scaler.data_min_ / (self.scaler.data_max_ - self.scaler.data_min_))

        # Sort by variance
        feature_names = [f"lab_{name}" for name in self.REFERENCE_RANGES.keys()]
        importance = sorted(
            zip(feature_names, variances),
            key=lambda x: x[1],
            reverse=True,
        )
        return importance


if __name__ == "__main__":
    # Example usage
    from data.loaders import DataLoader

    loader = DataLoader()
    loader.create_synthetic_dataset(n_samples=500)
    records = loader.load_patient_records("synthetic_patients.csv")
    df = loader.records_to_dataframe(records)

    extractor = LabFeatureExtractor(normalization="z_score", handle_missing="mean")
    df_transformed = extractor.fit_transform(df)

    print(f"Original shape: {df.shape}")
    print(f"Transformed shape: {df_transformed.shape}")
    print(f"\nNew features added:")
    new_cols = set(df_transformed.columns) - set(df.columns)
    for col in sorted(new_cols):
        print(f"  - {col}")
