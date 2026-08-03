"""Clinical NLP for free-text medical reports.

Naive keyword counting fails on clinical prose, because most of what a note
says about a finding is that it is *absent*: "no evidence of sepsis", "denies
chest pain", "ruled out MI". A counter reads those as positive evidence and
inverts the signal. This module resolves, for every matched concept:

  polarity     - affirmed / negated       ("no sepsis")
  experiencer  - patient / other          ("father had an MI")
  temporality  - current / historical     ("history of CHF")
  uncertainty  - certain / hedged         ("possible pneumonia")

Only concepts that are affirmed, about the patient, current and reasonably
certain count toward risk. The algorithm is NegEx/ConText (Chapman et al.),
which stays the standard for this because it is auditable — a clinician can be
shown exactly which trigger flipped a finding.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ConText trigger lexicons
# ---------------------------------------------------------------------------

# Triggers that negate concepts appearing AFTER them, up to a scope terminator.
PRECEDING_NEGATION = [
    "no evidence of", "no evidence for", "no sign of", "no signs of",
    "no suspicion of", "not consistent with", "no indication of",
    "without evidence of", "without any evidence of", "without indication of",
    "rules out", "ruled out", "rule out", "denies", "denied", "denying",
    "negative for", "free of", "absence of", "without", "not demonstrate",
    "no complaints of", "no longer", "resolved", "unremarkable for",
    "fails to reveal", "no", "not", "never",
]

# Triggers that negate concepts appearing BEFORE them.
FOLLOWING_NEGATION = [
    "is ruled out", "are ruled out", "was ruled out", "were ruled out",
    "has been ruled out", "have been ruled out", "is negative",
    "are negative", "was negative", "were negative", "not seen",
    "not present", "is absent", "are absent", "unlikely",
]

# Findings belong to somebody other than the patient.
EXPERIENCER_TRIGGERS = [
    "family history", "fh of", "mother", "father", "sister", "brother",
    "son", "daughter", "aunt", "uncle", "grandmother", "grandfather",
    "maternal", "paternal", "sibling", "cousin",
]

# Findings are in the past, not the current presentation.
HISTORICAL_TRIGGERS = [
    "history of", "hx of", "h/o", "past medical history", "pmh",
    "previous", "previously", "prior", "in the past", "status post",
    "s/p", "resolved", "years ago", "months ago", "childhood",
]

# The clinician is not committing to the finding.
UNCERTAINTY_TRIGGERS = [
    "possible", "possibly", "probable", "probably", "likely", "suspected",
    "suspicious for", "concern for", "concerning for", "question of",
    "questionable", "may be", "might be", "could be", "cannot exclude",
    "cannot rule out", "differential includes", "rule out", "vs.", "versus",
    "presumed", "apparent", "equivocal", "borderline",
]

# Words that end a trigger's scope. A negation does not survive past "but".
SCOPE_TERMINATORS = [
    "but", "however", "although", "though", "nevertheless", "yet",
    "except", "aside from", "apart from", "otherwise", "still",
    "which", "who", "unless",
]


# ---------------------------------------------------------------------------
# Concept lexicon
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClinicalConcept:
    """A findable clinical concept and what it contributes to risk."""

    name: str
    weight: float
    patterns: Tuple[str, ...]
    category: str = "finding"


# Weights are relative severity contributions, not probabilities. They are a
# prior for the auxiliary channel only — the model learns the final mapping.
CONCEPT_LEXICON: Tuple[ClinicalConcept, ...] = (
    # Organ failure / peri-arrest
    ClinicalConcept("cardiac_arrest", 5.0, ("cardiac arrest", "cardiopulmonary arrest", "asystole", "pea arrest"), "critical"),
    ClinicalConcept("septic_shock", 5.0, ("septic shock", "shock"), "critical"),
    ClinicalConcept("sepsis", 4.0, ("sepsis", "septic", "bacteremia", "septicemia"), "critical"),
    ClinicalConcept("respiratory_failure", 4.0, ("respiratory failure", "respiratory distress", "intubated", "mechanical ventilation", "ards"), "critical"),
    ClinicalConcept("multi_organ_failure", 5.0, ("multi-organ failure", "multiorgan failure", "mods"), "critical"),
    ClinicalConcept("renal_failure", 3.5, ("renal failure", "acute kidney injury", "aki", "anuria", "dialysis"), "critical"),
    ClinicalConcept("hepatic_failure", 3.5, ("liver failure", "hepatic failure", "encephalopathy", "cirrhosis"), "critical"),
    ClinicalConcept("dic", 4.0, ("disseminated intravascular coagulation", "dic"), "critical"),

    # Haemodynamic / neurological instability
    ClinicalConcept("hypotension", 3.0, ("hypotension", "hypotensive", "vasopressor", "pressors", "norepinephrine", "levophed"), "instability"),
    ClinicalConcept("altered_mental_status", 3.0, ("altered mental status", "unresponsive", "unconscious", "obtunded", "gcs", "delirium", "encephalopathic"), "instability"),
    ClinicalConcept("arrhythmia", 2.5, ("arrhythmia", "atrial fibrillation", "ventricular tachycardia", "bradycardia", "tachycardia"), "instability"),
    ClinicalConcept("hypoxia", 2.5, ("hypoxia", "hypoxemia", "desaturation", "spo2 low", "cyanosis"), "instability"),
    ClinicalConcept("hemorrhage", 3.0, ("hemorrhage", "haemorrhage", "active bleeding", "gi bleed", "melena", "hematemesis"), "instability"),

    # Acute presentations
    ClinicalConcept("myocardial_infarction", 3.0, ("myocardial infarction", "stemi", "nstemi", "acute coronary syndrome", "acs"), "acute"),
    ClinicalConcept("stroke", 3.0, ("stroke", "cva", "cerebrovascular accident", "intracranial hemorrhage"), "acute"),
    ClinicalConcept("pulmonary_embolism", 3.0, ("pulmonary embolism", "pe", "dvt", "deep vein thrombosis"), "acute"),
    ClinicalConcept("pneumonia", 2.0, ("pneumonia", "consolidation", "infiltrate"), "acute"),
    ClinicalConcept("infection", 1.5, ("infection", "cellulitis", "abscess", "uti", "fever", "febrile", "pyrexia"), "acute"),

    # Chronic burden
    ClinicalConcept("diabetes", 1.0, ("diabetes", "diabetic", "dm2", "t2dm", "iddm", "niddm"), "comorbidity"),
    ClinicalConcept("heart_failure", 1.5, ("heart failure", "chf", "cardiomyopathy", "reduced ejection fraction"), "comorbidity"),
    ClinicalConcept("copd", 1.2, ("copd", "emphysema", "chronic bronchitis"), "comorbidity"),
    ClinicalConcept("ckd", 1.5, ("chronic kidney disease", "ckd", "esrd", "end stage renal"), "comorbidity"),
    ClinicalConcept("malignancy", 1.5, ("cancer", "malignancy", "carcinoma", "metastatic", "lymphoma", "leukemia"), "comorbidity"),
    ClinicalConcept("immunosuppression", 1.5, ("immunosuppressed", "immunocompromised", "neutropenic", "chemotherapy", "transplant"), "comorbidity"),
    ClinicalConcept("hypertension", 0.8, ("hypertension", "htn"), "comorbidity"),

    # Protective / de-escalating
    ClinicalConcept("improving", -1.5, ("improving", "improved", "stable", "afebrile", "recovering", "ambulating", "tolerating"), "protective"),
    ClinicalConcept("discharge_ready", -2.0, ("discharge", "discharged home", "ready for discharge", "cleared for discharge"), "protective"),
)


# ---------------------------------------------------------------------------
# Note section handling
# ---------------------------------------------------------------------------

SECTION_HEADERS = {
    "chief_complaint": ("chief complaint", "cc", "presenting complaint", "reason for visit"),
    "hpi": ("history of present illness", "hpi", "history of presenting illness"),
    "past_medical_history": ("past medical history", "pmh", "medical history"),
    "family_history": ("family history", "fh", "social and family history"),
    "medications": ("medications", "meds", "current medications", "home medications"),
    "allergies": ("allergies", "allergy"),
    "physical_exam": ("physical exam", "physical examination", "examination", "pe"),
    "assessment": ("assessment", "impression", "assessment and plan", "a/p"),
    "plan": ("plan", "recommendations", "disposition"),
}

# Sections that describe someone or something other than the current illness.
NON_PATIENT_SECTIONS = {"family_history"}
HISTORICAL_SECTIONS = {"past_medical_history", "allergies", "medications"}


@dataclass
class ConceptMention:
    """One matched concept, with its ConText attributes resolved."""

    concept: str
    category: str
    weight: float
    text: str
    start: int
    end: int
    section: str = "unknown"
    negated: bool = False
    historical: bool = False
    other_experiencer: bool = False
    uncertain: bool = False

    @property
    def is_active(self) -> bool:
        """True when the mention describes the patient's current, real state.

        Comorbidities are exempt from the historical filter: a chronic disease
        is recorded in the past-history section by definition, and zeroing it
        there would discard exactly the background risk it represents.
        """
        if self.negated or self.other_experiencer:
            return False
        if self.historical and self.category != "comorbidity":
            return False
        return True

    @property
    def effective_weight(self) -> float:
        """Weight after ConText attenuation."""
        if not self.is_active:
            return 0.0
        # A hedged finding is real evidence, just weaker than a committed one.
        return self.weight * (0.5 if self.uncertain else 1.0)


class ClinicalTextProcessor:
    """Section-aware NegEx/ConText concept extractor for clinical notes."""

    def __init__(
        self,
        lexicon: Sequence[ClinicalConcept] = CONCEPT_LEXICON,
        scope_window: int = 60,
    ):
        """
        Args:
            lexicon: concepts to search for.
            scope_window: characters a trigger's influence extends, unless a
                scope terminator or sentence boundary cuts it short first.
        """
        self.lexicon = tuple(lexicon)
        self.scope_window = scope_window
        self._concept_patterns = self._compile_concepts(self.lexicon)
        self._preceding_neg = self._compile_triggers(PRECEDING_NEGATION)
        self._following_neg = self._compile_triggers(FOLLOWING_NEGATION)
        self._experiencer = self._compile_triggers(EXPERIENCER_TRIGGERS)
        self._historical = self._compile_triggers(HISTORICAL_TRIGGERS)
        self._uncertain = self._compile_triggers(UNCERTAINTY_TRIGGERS)
        self._terminators = self._compile_triggers(SCOPE_TERMINATORS)
        self._section_pattern = self._compile_sections()

    @staticmethod
    def _compile_triggers(triggers: Sequence[str]) -> re.Pattern:
        # Longest-first so "no evidence of" wins over the bare "no" it contains.
        ordered = sorted(triggers, key=len, reverse=True)
        joined = "|".join(re.escape(t) for t in ordered)
        return re.compile(rf"\b({joined})\b", re.IGNORECASE)

    @staticmethod
    def _compile_concepts(
        lexicon: Sequence[ClinicalConcept],
    ) -> List[Tuple[ClinicalConcept, re.Pattern]]:
        compiled = []
        for concept in lexicon:
            ordered = sorted(concept.patterns, key=len, reverse=True)
            joined = "|".join(re.escape(p) for p in ordered)
            compiled.append((concept, re.compile(rf"\b({joined})\b", re.IGNORECASE)))
        return compiled

    @staticmethod
    def _compile_sections() -> re.Pattern:
        headers = [h for aliases in SECTION_HEADERS.values() for h in aliases]
        headers.sort(key=len, reverse=True)
        joined = "|".join(re.escape(h) for h in headers)
        # A header is a line-initial label followed by a colon.
        return re.compile(rf"^\s*({joined})\s*:", re.IGNORECASE | re.MULTILINE)

    # -- section segmentation ------------------------------------------------

    def segment_sections(self, text: str) -> List[Tuple[str, int, int]]:
        """Split a note into (section_name, start, end) spans."""
        matches = list(self._section_pattern.finditer(text))
        if not matches:
            return [("unknown", 0, len(text))]

        alias_to_section = {
            alias.lower(): name
            for name, aliases in SECTION_HEADERS.items()
            for alias in aliases
        }

        spans = []
        if matches[0].start() > 0:
            spans.append(("unknown", 0, matches[0].start()))

        for i, match in enumerate(matches):
            section = alias_to_section.get(match.group(1).strip().lower(), "unknown")
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            spans.append((section, match.end(), end))

        return spans

    def _section_at(self, spans: Sequence[Tuple[str, int, int]], pos: int) -> str:
        for name, start, end in spans:
            if start <= pos < end:
                return name
        return "unknown"

    # -- ConText scope resolution -------------------------------------------

    def _sentence_bounds(self, text: str, pos: int) -> Tuple[int, int]:
        """Sentence containing pos. Triggers never cross sentence boundaries."""
        start = max(
            (text.rfind(p, 0, pos) for p in (". ", "\n", "; ", "! ", "? ")),
            default=-1,
        )
        end_candidates = [
            e for e in (text.find(p, pos) for p in (". ", "\n", "; ", "! ", "? ")) if e != -1
        ]
        return (start + 1 if start != -1 else 0,
                min(end_candidates) if end_candidates else len(text))

    def _trigger_applies(
        self,
        text: str,
        pattern: re.Pattern,
        concept_start: int,
        concept_end: int,
        direction: str,
    ) -> bool:
        """Does a trigger of this type govern the concept at this position?

        Scope runs from the trigger to the concept and is cut by the sentence
        boundary, the window size, or an intervening scope terminator.
        """
        sent_start, sent_end = self._sentence_bounds(text, concept_start)

        if direction == "preceding":
            window_start = max(sent_start, concept_start - self.scope_window)
            region = text[window_start:concept_start]
            offset = window_start
            for match in pattern.finditer(region):
                between = text[offset + match.end() : concept_start]
                if not self._terminators.search(between):
                    return True
            return False

        window_end = min(sent_end, concept_end + self.scope_window)
        region = text[concept_end:window_end]
        for match in pattern.finditer(region):
            between = text[concept_end : concept_end + match.start()]
            if not self._terminators.search(between):
                return True
        return False

    # -- extraction ----------------------------------------------------------

    def extract(self, text: Optional[str]) -> List[ConceptMention]:
        """Find every concept mention and resolve its ConText attributes."""
        if not text or pd.isna(text):
            return []

        text = str(text)
        sections = self.segment_sections(text)
        mentions: List[ConceptMention] = []

        for concept, pattern in self._concept_patterns:
            for match in pattern.finditer(text):
                start, end = match.start(), match.end()
                section = self._section_at(sections, start)

                mention = ConceptMention(
                    concept=concept.name,
                    category=concept.category,
                    weight=concept.weight,
                    text=match.group(0),
                    start=start,
                    end=end,
                    section=section,
                    negated=(
                        self._trigger_applies(text, self._preceding_neg, start, end, "preceding")
                        or self._trigger_applies(text, self._following_neg, start, end, "following")
                    ),
                    historical=(
                        section in HISTORICAL_SECTIONS
                        or self._trigger_applies(text, self._historical, start, end, "preceding")
                    ),
                    other_experiencer=(
                        section in NON_PATIENT_SECTIONS
                        or self._trigger_applies(text, self._experiencer, start, end, "preceding")
                    ),
                    uncertain=self._trigger_applies(
                        text, self._uncertain, start, end, "preceding"
                    ),
                )
                mentions.append(mention)

        return self._deduplicate(mentions)

    @staticmethod
    def _deduplicate(mentions: List[ConceptMention]) -> List[ConceptMention]:
        """Drop mentions contained inside a longer overlapping match.

        "septic shock" also matches the `sepsis` pattern "septic"; keeping both
        double-counts one finding.
        """
        ordered = sorted(mentions, key=lambda m: (m.start, -(m.end - m.start)))
        kept: List[ConceptMention] = []
        for mention in ordered:
            if any(
                k.start <= mention.start and mention.end <= k.end and k is not mention
                for k in kept
            ):
                continue
            kept.append(mention)
        return kept


# ---------------------------------------------------------------------------
# Feature construction
# ---------------------------------------------------------------------------

class ClinicalNLPFeaturizer:
    """Turns notes into a numeric feature block via ConText-resolved concepts."""

    def __init__(
        self,
        processor: Optional[ClinicalTextProcessor] = None,
        include_concept_indicators: bool = True,
    ):
        self.processor = processor or ClinicalTextProcessor()
        self.include_concept_indicators = include_concept_indicators
        self.fitted = False
        self._concept_names = [c.name for c in self.processor.lexicon]
        self._categories = sorted({c.category for c in self.processor.lexicon})

    def fit(self, df: pd.DataFrame, text_column: str = "medical_report") -> "ClinicalNLPFeaturizer":
        self.fitted = True
        return self

    def transform(
        self, df: pd.DataFrame, text_column: str = "medical_report"
    ) -> pd.DataFrame:
        if not self.fitted:
            raise ValueError("Featurizer must be fitted first")

        if text_column not in df.columns:
            logger.warning("No %s column; skipping clinical NLP features", text_column)
            return df.copy()

        rows = [self._featurize_one(text) for text in df[text_column]]
        features = pd.DataFrame(rows, index=df.index)
        return pd.concat([df, features], axis=1)

    def fit_transform(
        self, df: pd.DataFrame, text_column: str = "medical_report"
    ) -> pd.DataFrame:
        return self.fit(df, text_column).transform(df, text_column)

    def _featurize_one(self, text: Optional[str]) -> Dict[str, float]:
        mentions = self.processor.extract(text)
        features: Dict[str, float] = {}

        active = [m for m in mentions if m.is_active]

        # Score each concept once. A note repeating "hypotensive ... started on
        # norepinephrine" describes one episode of hypotension, not two, and
        # summing every mention would let verbose notes outscore sick patients.
        strongest: Dict[str, ConceptMention] = {}
        for mention in active:
            current = strongest.get(mention.concept)
            if current is None or abs(mention.effective_weight) > abs(current.effective_weight):
                strongest[mention.concept] = mention
        unique_active = list(strongest.values())

        # Aggregate risk, split into the part that adds risk and the part that
        # removes it — a note can contain both, and their sum hides that.
        positive = sum(m.effective_weight for m in unique_active if m.effective_weight > 0)
        negative = sum(m.effective_weight for m in unique_active if m.effective_weight < 0)

        features["nlp_risk_positive"] = positive
        features["nlp_risk_protective"] = abs(negative)
        features["nlp_risk_net"] = positive + negative

        # Counts by ConText attribute — how much of the note is denial vs finding.
        features["nlp_mentions_total"] = float(len(mentions))
        features["nlp_mentions_active"] = float(len(unique_active))
        features["nlp_mentions_negated"] = float(sum(m.negated for m in mentions))
        features["nlp_mentions_historical"] = float(sum(m.historical for m in mentions))
        features["nlp_mentions_family"] = float(sum(m.other_experiencer for m in mentions))
        features["nlp_mentions_uncertain"] = float(sum(m.uncertain for m in mentions))

        # Fraction of findings the clinician explicitly ruled out. A note that is
        # mostly denials reads very differently from one that is mostly findings.
        features["nlp_negation_ratio"] = (
            features["nlp_mentions_negated"] / len(mentions) if mentions else 0.0
        )

        # Per-category active weight.
        for category in self._categories:
            features[f"nlp_cat_{category}"] = sum(
                m.effective_weight for m in unique_active if m.category == category
            )

        features["nlp_severity_level"] = self._severity_level(unique_active)
        features["nlp_comorbidity_count"] = float(
            sum(m.category == "comorbidity" for m in unique_active)
        )
        features["nlp_text_length"] = float(len(str(text).split())) if text and pd.notna(text) else 0.0

        if self.include_concept_indicators:
            present = set(strongest)
            for name in self._concept_names:
                features[f"nlp_has_{name}"] = float(name in present)

        return features

    @staticmethod
    def _severity_level(active: Sequence[ConceptMention]) -> float:
        """Ordinal severity from the most severe active category present."""
        categories = {m.category for m in active if m.effective_weight > 0}
        if "critical" in categories:
            return 4.0
        if "instability" in categories:
            return 3.0
        if "acute" in categories:
            return 2.0
        if "comorbidity" in categories:
            return 1.0
        return 0.0

    def explain(self, text: str) -> pd.DataFrame:
        """Per-mention breakdown, for auditing why a note scored as it did."""
        mentions = self.processor.extract(text)
        return pd.DataFrame(
            [
                {
                    "concept": m.concept,
                    "matched_text": m.text,
                    "section": m.section,
                    "negated": m.negated,
                    "historical": m.historical,
                    "family": m.other_experiencer,
                    "uncertain": m.uncertain,
                    "active": m.is_active,
                    "weight": m.effective_weight,
                }
                for m in mentions
            ]
        )


# ---------------------------------------------------------------------------
# Contextual embeddings
# ---------------------------------------------------------------------------

class ClinicalEmbeddingExtractor:
    """Sentence embeddings from a clinically pre-trained transformer.

    Bio_ClinicalBERT is pre-trained on MIMIC-III notes, so it has seen clinical
    abbreviations ("s/p", "w/o", "pt") that general-domain BERT tokenizes into
    noise. Falls back to hashed TF-IDF when transformers is unavailable, so the
    pipeline still runs in a minimal install.
    """

    DEFAULT_MODEL = "emilyalsentzer/Bio_ClinicalBERT"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        max_length: int = 512,
        batch_size: int = 16,
        n_components: int = 64,
    ):
        self.model_name = model_name
        self.max_length = max_length
        self.batch_size = batch_size
        self.n_components = n_components
        self.model = None
        self.tokenizer = None
        self._torch = None
        self._fallback = None
        self.fitted = False

    def fit(self, df: pd.DataFrame, text_column: str = "medical_report") -> "ClinicalEmbeddingExtractor":
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer

            self._torch = torch
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModel.from_pretrained(self.model_name)
            self.model.eval()
            logger.info("Loaded clinical embedding model %s", self.model_name)
        except Exception as exc:
            logger.warning(
                "Transformer unavailable (%s); falling back to TF-IDF + SVD", exc
            )
            self._fit_fallback(df, text_column)

        self.fitted = True
        return self

    def _fit_fallback(self, df: pd.DataFrame, text_column: str) -> None:
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.pipeline import make_pipeline

        texts = df[text_column].fillna("").astype(str) if text_column in df else pd.Series([""])
        # SVD cannot produce more components than the term matrix has columns.
        n_components = max(2, min(self.n_components, len(texts) - 1))
        self._fallback = make_pipeline(
            TfidfVectorizer(
                ngram_range=(1, 2), min_df=2, max_features=50_000, sublinear_tf=True
            ),
            TruncatedSVD(n_components=n_components, random_state=42),
        )
        self._fallback.fit(texts)

    def transform(
        self, df: pd.DataFrame, text_column: str = "medical_report"
    ) -> np.ndarray:
        if not self.fitted:
            raise ValueError("Embedding extractor must be fitted first")

        texts = (
            df[text_column].fillna("").astype(str).tolist()
            if text_column in df.columns
            else [""] * len(df)
        )

        if self.model is None:
            return self._fallback.transform(texts)

        torch = self._torch
        vectors = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            encoded = self.tokenizer(
                batch,
                return_tensors="pt",
                truncation=True,
                max_length=self.max_length,
                padding=True,
            )
            with torch.no_grad():
                output = self.model(**encoded).last_hidden_state

            # Mean-pool over real tokens only; padding would drag vectors toward
            # each other and wash out the differences between notes.
            mask = encoded["attention_mask"].unsqueeze(-1).float()
            pooled = (output * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            vectors.append(pooled.numpy())

        return np.vstack(vectors)

    def fit_transform(
        self, df: pd.DataFrame, text_column: str = "medical_report"
    ) -> np.ndarray:
        return self.fit(df, text_column).transform(df, text_column)


def add_embedding_columns(
    df: pd.DataFrame, embeddings: np.ndarray, prefix: str = "emb"
) -> pd.DataFrame:
    """Attach an embedding matrix to a frame as ``{prefix}_000`` columns."""
    block = pd.DataFrame(
        embeddings,
        index=df.index,
        columns=[f"{prefix}_{i:03d}" for i in range(embeddings.shape[1])],
    )
    return pd.concat([df, block], axis=1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    notes = [
        "Chief complaint: fever.\nHPI: 68M with possible pneumonia. No evidence "
        "of sepsis. Denies chest pain.\nPMH: diabetes, CHF.\n"
        "Family history: father had myocardial infarction.\n"
        "Assessment: hypotensive, started on norepinephrine.",
        "Chief complaint: follow-up.\nHPI: Patient is improving and afebrile. "
        "History of COPD. Ready for discharge.",
    ]

    featurizer = ClinicalNLPFeaturizer()
    frame = pd.DataFrame({"medical_report": notes})
    out = featurizer.fit_transform(frame)

    print(out[[
        "nlp_risk_net",
        "nlp_mentions_active",
        "nlp_mentions_negated",
        "nlp_severity_level",
    ]])
    print("\nMention-level audit for note 1:")
    print(featurizer.explain(notes[0]).to_string(index=False))
