"""Clinical features extraction from medical reports."""

import re
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class ClinicalFeatureExtractor:
    """Extracts features from clinical text (medical reports)."""

    # Clinical keywords indicating deterioration risk
    RISK_KEYWORDS = {
        "high": [
            "critical",
            "severe",
            "acute",
            "emergency",
            "sepsis",
            "shock",
            "respiratory distress",
            "altered mental status",
            "unconscious",
            "organ failure",
            "renal failure",
            "liver failure",
            "cardiac arrest",
        ],
        "medium": [
            "infection",
            "fever",
            "hypoxia",
            "arrhythmia",
            "hypertension",
            "hypotension",
            "bleeding",
            "dehydration",
            "anemia",
            "confusion",
            "weakness",
        ],
        "low": [
            "mild",
            "stable",
            "improving",
            "recovery",
            "discharged",
        ],
    }

    # Comorbidities that increase risk
    COMORBIDITIES = {
        "diabetes": 1.2,
        "heart disease": 1.3,
        "hypertension": 1.1,
        "kidney disease": 1.4,
        "liver disease": 1.3,
        "cancer": 1.2,
        "copd": 1.2,
        "pneumonia": 1.3,
        "asthma": 1.1,
    }

    def __init__(self):
        """Initialize clinical feature extractor."""
        self.fitted = False

    def fit(self, df: pd.DataFrame) -> "ClinicalFeatureExtractor":
        """Fit the feature extractor (minimal fitting needed for text analysis).

        Args:
            df: DataFrame with medical_report column

        Returns:
            self
        """
        self.fitted = True
        logger.info("Clinical feature extractor fitted")
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform clinical text into features.

        Args:
            df: DataFrame with optional medical_report column

        Returns:
            DataFrame with added clinical features
        """
        if not self.fitted:
            raise ValueError("Feature extractor must be fitted first")

        df_result = df.copy()

        if "medical_report" not in df_result.columns:
            logger.warning("No medical_report column found, skipping clinical features")
            return df_result

        # Extract text features
        df_result["clinical_risk_score"] = df_result["medical_report"].apply(
            self._extract_risk_score
        )
        df_result["clinical_severity_level"] = df_result["medical_report"].apply(
            self._extract_severity_level
        )
        df_result["comorbidity_count"] = df_result["medical_report"].apply(
            self._count_comorbidities
        )
        df_result["comorbidity_risk_factor"] = df_result["medical_report"].apply(
            self._calculate_comorbidity_risk
        )
        df_result["text_length"] = df_result["medical_report"].apply(
            lambda x: len(str(x).split()) if pd.notna(x) else 0
        )
        df_result["clinical_keywords_count"] = df_result["medical_report"].apply(
            self._count_risk_keywords
        )

        # Normalize risk score to 0-1
        if df_result["clinical_risk_score"].max() > 0:
            df_result["clinical_risk_score_normalized"] = (
                df_result["clinical_risk_score"]
                / df_result["clinical_risk_score"].max()
            )
        else:
            df_result["clinical_risk_score_normalized"] = 0.0

        logger.info("Clinical features extracted")
        return df_result

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fit and transform in one step.

        Args:
            df: DataFrame with medical_report column

        Returns:
            DataFrame with clinical features added
        """
        return self.fit(df).transform(df)

    def _extract_risk_score(self, text: Optional[str]) -> float:
        """Extract risk score from clinical text.

        Args:
            text: Medical report text

        Returns:
            Risk score (higher = more risky)
        """
        if not text or pd.isna(text):
            return 0.0

        text_lower = str(text).lower()
        score = 0.0

        # Count high-risk keywords
        for keyword in self.RISK_KEYWORDS["high"]:
            count = text_lower.count(keyword)
            score += count * 3.0

        # Count medium-risk keywords
        for keyword in self.RISK_KEYWORDS["medium"]:
            count = text_lower.count(keyword)
            score += count * 1.0

        # Subtract for positive keywords
        for keyword in self.RISK_KEYWORDS["low"]:
            count = text_lower.count(keyword)
            score -= count * 0.5

        return max(0.0, score)

    def _extract_severity_level(self, text: Optional[str]) -> int:
        """Extract severity level from text.

        Args:
            text: Medical report text

        Returns:
            Severity level: 0=unknown, 1=low, 2=medium, 3=high, 4=critical
        """
        if not text or pd.isna(text):
            return 0

        text_lower = str(text).lower()

        # Check for critical indicators
        critical_words = ["critical", "emergency", "intensive care", "icu", "cardiac arrest"]
        if any(word in text_lower for word in critical_words):
            return 4

        # Check for high severity
        high_words = [
            "severe",
            "acute",
            "organ failure",
            "sepsis",
            "shock",
            "respiratory distress",
        ]
        if any(word in text_lower for word in high_words):
            return 3

        # Check for medium severity
        medium_words = ["infection", "fever", "hypoxia", "bleeding", "confusion"]
        if any(word in text_lower for word in medium_words):
            return 2

        # Check for low severity
        if any(word in text_lower for word in self.RISK_KEYWORDS["low"]):
            return 1

        return 0

    def _count_comorbidities(self, text: Optional[str]) -> int:
        """Count number of comorbidities mentioned in text.

        Args:
            text: Medical report text

        Returns:
            Number of comorbidities found
        """
        if not text or pd.isna(text):
            return 0

        text_lower = str(text).lower()
        count = sum(1 for comorbidity in self.COMORBIDITIES if comorbidity in text_lower)
        return count

    def _calculate_comorbidity_risk(self, text: Optional[str]) -> float:
        """Calculate combined risk factor from comorbidities.

        Args:
            text: Medical report text

        Returns:
            Risk factor (multiplicative: >1 means increased risk)
        """
        if not text or pd.isna(text):
            return 1.0

        text_lower = str(text).lower()
        risk_factor = 1.0

        for comorbidity, factor in self.COMORBIDITIES.items():
            if comorbidity in text_lower:
                risk_factor *= factor

        return risk_factor

    def _count_risk_keywords(self, text: Optional[str]) -> int:
        """Count total number of risk keywords in text.

        Args:
            text: Medical report text

        Returns:
            Number of risk keywords found
        """
        if not text or pd.isna(text):
            return 0

        text_lower = str(text).lower()
        count = 0

        for keyword_list in self.RISK_KEYWORDS.values():
            for keyword in keyword_list:
                count += text_lower.count(keyword)

        return count


class TextEmbeddingExtractor:
    """Extracts embeddings from clinical text using pre-trained models."""

    def __init__(self, model_name: str = "distilbert-base-uncased"):
        """Initialize text embedding extractor.

        Args:
            model_name: Name of pre-trained model from HuggingFace
        """
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        self.fitted = False

        try:
            from transformers import AutoTokenizer, AutoModel

            self.AutoTokenizer = AutoTokenizer
            self.AutoModel = AutoModel
        except ImportError:
            logger.warning(
                "transformers library not installed. "
                "Text embeddings will not be available. "
                "Install with: pip install transformers"
            )

    def fit(self, df: pd.DataFrame) -> "TextEmbeddingExtractor":
        """Load pre-trained model.

        Args:
            df: DataFrame (used for consistency but not needed)

        Returns:
            self
        """
        if self.AutoTokenizer is None:
            logger.warning("Cannot fit embedder without transformers library")
            return self

        self.tokenizer = self.AutoTokenizer.from_pretrained(self.model_name)
        self.model = self.AutoModel.from_pretrained(self.model_name)
        self.fitted = True
        logger.info(f"Loaded embedding model: {self.model_name}")
        return self

    def transform(self, df: pd.DataFrame, text_column: str = "medical_report") -> np.ndarray:
        """Extract embeddings from text.

        Args:
            df: DataFrame with text column
            text_column: Name of column with text

        Returns:
            Array of embeddings (n_samples, embedding_dim)
        """
        if not self.fitted or self.model is None:
            logger.warning("Embedder not fitted, returning zeros")
            return np.zeros((len(df), 768))  # Default distilbert embedding size

        embeddings = []

        for text in df[text_column]:
            if pd.isna(text):
                embeddings.append(np.zeros(768))
                continue

            try:
                inputs = self.tokenizer(
                    str(text),
                    return_tensors="pt",
                    truncation=True,
                    max_length=512,
                )

                with torch.no_grad():
                    outputs = self.model(**inputs)
                    # Use [CLS] token embedding
                    embedding = outputs.last_hidden_state[:, 0, :].numpy()[0]

                embeddings.append(embedding)
            except Exception as e:
                logger.warning(f"Error processing text: {e}")
                embeddings.append(np.zeros(768))

        return np.array(embeddings)

    def fit_transform(self, df: pd.DataFrame) -> np.ndarray:
        """Fit and transform in one step."""
        return self.fit(df).transform(df)


if __name__ == "__main__":
    # Example usage
    data = {
        "patient_id": ["P1", "P2", "P3", "P4"],
        "medical_report": [
            "Patient with severe infection and sepsis, critical condition",
            "Stable patient, recovering well",
            "Mild fever, infection being treated",
            "Patient with diabetes and heart disease, improving",
        ],
    }

    df = pd.DataFrame(data)

    extractor = ClinicalFeatureExtractor()
    df_transformed = extractor.fit_transform(df)

    print("Clinical features extracted:")
    print(df_transformed[[
        "patient_id",
        "clinical_risk_score",
        "clinical_severity_level",
        "comorbidity_count",
    ]])
