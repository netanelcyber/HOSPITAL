"""Data loading utilities for patient data."""

import os
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
import pandas as pd
import numpy as np
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class PatientRecord:
    """Represents a single patient record with lab tests and medical report."""

    patient_id: str
    lab_tests: Dict[str, float]  # e.g., {'glucose': 110.5, 'hemoglobin': 12.3}
    medical_report: Optional[str] = None  # Free text clinical notes
    deteriorated: Optional[bool] = None  # Target variable
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "patient_id": self.patient_id,
            "lab_tests": self.lab_tests,
            "medical_report": self.medical_report,
            "deteriorated": self.deteriorated,
            "timestamp": self.timestamp,
            "metadata": self.metadata or {},
        }


class DataLoader:
    """Loads and manages patient data."""

    def __init__(self, data_dir: str = "data"):
        """Initialize data loader.

        Args:
            data_dir: Root directory for data files
        """
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw"
        self.processed_dir = self.data_dir / "processed"

        # Create directories if they don't exist
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def load_csv(self, filename: str) -> pd.DataFrame:
        """Load data from CSV file.

        Args:
            filename: CSV filename in raw data directory

        Returns:
            DataFrame with loaded data
        """
        filepath = self.raw_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        logger.info(f"Loading data from {filepath}")
        df = pd.read_csv(filepath)
        logger.info(f"Loaded {len(df)} records")
        return df

    def load_patient_records(
        self, csv_filename: str = "patients.csv"
    ) -> List[PatientRecord]:
        """Load patient records from CSV.

        Expected CSV columns:
        - patient_id
        - lab_test_<name> (e.g., lab_test_glucose, lab_test_hemoglobin)
        - medical_report (optional text)
        - deteriorated (target, optional)
        """
        df = self.load_csv(csv_filename)
        records = []

        for _, row in df.iterrows():
            # Extract lab test values
            lab_tests = {}
            for col in df.columns:
                if col.startswith("lab_test_"):
                    test_name = col.replace("lab_test_", "")
                    value = row[col]
                    if pd.notna(value):
                        lab_tests[test_name] = float(value)

            # Extract medical report
            medical_report = None
            if "medical_report" in df.columns:
                medical_report = row.get("medical_report")

            # Extract target variable
            deteriorated = None
            if "deteriorated" in df.columns:
                val = row.get("deteriorated")
                if pd.notna(val):
                    deteriorated = bool(int(val))

            # Extract timestamp
            timestamp = row.get("timestamp") if "timestamp" in df.columns else None

            record = PatientRecord(
                patient_id=str(row["patient_id"]),
                lab_tests=lab_tests,
                medical_report=medical_report,
                deteriorated=deteriorated,
                timestamp=timestamp,
            )
            records.append(record)

        logger.info(f"Loaded {len(records)} patient records")
        return records

    def records_to_dataframe(
        self, records: List[PatientRecord], include_lab: bool = True
    ) -> pd.DataFrame:
        """Convert patient records to DataFrame.

        Args:
            records: List of PatientRecord objects
            include_lab: Whether to include lab test columns

        Returns:
            DataFrame with patient data
        """
        data = []
        lab_columns = set()

        for record in records:
            row = {"patient_id": record.patient_id}

            # Add lab tests as separate columns
            if include_lab:
                for test_name, value in record.lab_tests.items():
                    row[f"lab_{test_name}"] = value
                    lab_columns.add(f"lab_{test_name}")

            # Add medical report
            if record.medical_report:
                row["medical_report"] = record.medical_report

            # Add target
            if record.deteriorated is not None:
                row["deteriorated"] = record.deteriorated

            if record.timestamp:
                row["timestamp"] = record.timestamp

            data.append(row)

        df = pd.DataFrame(data)

        # Fill missing lab values with NaN
        for col in lab_columns:
            if col not in df.columns:
                df[col] = np.nan

        logger.info(f"Created DataFrame with {len(df)} records and {len(df.columns)} columns")
        return df

    def save_processed_data(
        self, df: pd.DataFrame, filename: str = "processed_data.csv"
    ) -> None:
        """Save processed data to CSV.

        Args:
            df: DataFrame to save
            filename: Output filename in processed directory
        """
        filepath = self.processed_dir / filename
        df.to_csv(filepath, index=False)
        logger.info(f"Saved processed data to {filepath}")

    def create_synthetic_dataset(
        self,
        n_samples: int = 1000,
        output_filename: str = "synthetic_patients.csv",
    ) -> pd.DataFrame:
        """Create synthetic patient dataset for testing.

        Args:
            n_samples: Number of synthetic records to create
            output_filename: CSV filename to save to

        Returns:
            DataFrame with synthetic data
        """
        np.random.seed(42)

        lab_tests = {
            "glucose": np.random.normal(110, 30, n_samples),
            "hemoglobin": np.random.normal(13, 2, n_samples),
            "potassium": np.random.normal(4.0, 0.5, n_samples),
            "sodium": np.random.normal(138, 5, n_samples),
            "creatinine": np.random.normal(0.8, 0.3, n_samples),
            "blood_urea_nitrogen": np.random.normal(18, 8, n_samples),
            "platelet_count": np.random.normal(250, 60, n_samples),
            "white_blood_cell_count": np.random.normal(7.5, 3, n_samples),
        }

        # Target variable: higher risk with abnormal lab values
        risk_score = np.zeros(n_samples)
        for test_name, values in lab_tests.items():
            # Abnormal values increase risk
            z_scores = np.abs((values - np.mean(values)) / np.std(values))
            risk_score += z_scores

        risk_score /= len(lab_tests)
        deteriorated = (risk_score > np.percentile(risk_score, 70)).astype(int)

        df = pd.DataFrame(
            {
                "patient_id": [f"PAT_{i:06d}" for i in range(n_samples)],
                "deteriorated": deteriorated,
                "medical_report": [
                    f"Patient with lab abnormalities. Risk score: {s:.2f}"
                    for s in risk_score
                ],
            }
        )

        # Add lab test columns
        for test_name, values in lab_tests.items():
            df[f"lab_test_{test_name}"] = np.maximum(0, values)  # Keep values positive

        # Save to raw data directory
        output_path = self.raw_dir / output_filename
        df.to_csv(output_path, index=False)
        logger.info(f"Created synthetic dataset with {n_samples} records at {output_path}")

        return df


if __name__ == "__main__":
    # Example usage
    loader = DataLoader()

    # Create synthetic data
    loader.create_synthetic_dataset(n_samples=1000)

    # Load data
    records = loader.load_patient_records("synthetic_patients.csv")
    print(f"Loaded {len(records)} records")

    # Convert to DataFrame
    df = loader.records_to_dataframe(records)
    print(f"DataFrame shape: {df.shape}")
    print(f"\nColumns: {list(df.columns)}")
    print(f"\nFirst few rows:\n{df.head()}")
    print(f"\nTarget distribution:\n{df['deteriorated'].value_counts()}")
