"""NCBI data sources: GEO cohorts and PubMed/MeSH lexicon expansion.

Two distinct uses, and it is worth being precise about which is which:

1. **GEO (Gene Expression Omnibus)** hosts critical-illness cohorts whose
   samples carry outcome annotations (ICU mortality, sepsis severity, organ
   failure). These are *transcriptomic*, not clinical chemistry — a GEO series
   does not contain a creatinine value. They are useful here as external
   validation cohorts and as a source of outcome-labelled phenotype tables,
   not as a drop-in replacement for the lab panel. Where a series records
   clinical covariates in its sample characteristics, those are extracted.

2. **PubMed / MeSH** supply the terminology used to expand the clinical NLP
   lexicon. MeSH entry terms give the synonym sets ("MI", "myocardial
   infarct", "heart attack") that a hand-written lexicon always misses.

Network access to `eutils.ncbi.nlm.nih.gov` is required. NCBI rate-limits to
3 requests/second without an API key and 10/second with one; set NCBI_API_KEY
to get the higher limit. Responses are cached on disk, because these endpoints
are slow and the same query gets re-run constantly during development.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
GEO_FTP_BASE = "https://ftp.ncbi.nlm.nih.gov/geo/series"


class NCBIRateLimiter:
    """Spaces requests to stay under NCBI's published per-second limit.

    Exceeding it gets the caller's IP blocked, not just throttled, so this is
    enforced rather than advisory.
    """

    def __init__(self, requests_per_second: float):
        self.min_interval = 1.0 / requests_per_second
        self._last_request = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()


class NCBIClient:
    """Cached, rate-limited E-utilities client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        email: Optional[str] = None,
        tool: str = "hospital-deterioration-prediction",
        cache_dir: str | Path = "data/raw/ncbi_cache",
        timeout: int = 60,
    ):
        self.api_key = api_key or os.environ.get("NCBI_API_KEY")
        self.email = email or os.environ.get("NCBI_EMAIL")
        self.tool = tool
        self.timeout = timeout
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # NCBI grants 10 req/s to keyed callers, 3/s otherwise.
        self.limiter = NCBIRateLimiter(10.0 if self.api_key else 3.0)

    def _identity_params(self) -> Dict[str, str]:
        params = {"tool": self.tool}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.email:
            params["email"] = self.email
        return params

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()[:32]
        return self.cache_dir / f"{digest}.cache"

    def _get(self, endpoint: str, params: Dict[str, str], use_cache: bool = True) -> bytes:
        query = {**params, **self._identity_params()}
        url = f"{EUTILS_BASE}/{endpoint}?{urllib.parse.urlencode(query)}"

        # Cache key excludes credentials so a key rotation doesn't invalidate it.
        cache_key = f"{endpoint}?{urllib.parse.urlencode(params)}"
        cache_path = self._cache_path(cache_key)
        if use_cache and cache_path.exists():
            return cache_path.read_bytes()

        self.limiter.wait()
        logger.debug("GET %s", endpoint)
        request = urllib.request.Request(url, headers={"User-Agent": self.tool})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = response.read()

        if use_cache:
            cache_path.write_bytes(payload)
        return payload

    def esearch(self, db: str, term: str, retmax: int = 100) -> List[str]:
        """Return record UIDs matching a query."""
        payload = self._get(
            "esearch.fcgi",
            {"db": db, "term": term, "retmax": str(retmax), "retmode": "json"},
        )
        data = json.loads(payload)
        return data.get("esearchresult", {}).get("idlist", [])

    def esummary(self, db: str, uids: Sequence[str]) -> List[Dict]:
        """Return document summaries for UIDs."""
        if not uids:
            return []
        payload = self._get(
            "esummary.fcgi",
            {"db": db, "id": ",".join(uids), "retmode": "json"},
        )
        data = json.loads(payload).get("result", {})
        return [data[uid] for uid in data.get("uids", []) if uid in data]

    def efetch(self, db: str, uids: Sequence[str], rettype: str = "xml") -> bytes:
        """Return full records for UIDs."""
        if not uids:
            return b""
        return self._get(
            "efetch.fcgi",
            {"db": db, "id": ",".join(uids), "rettype": rettype, "retmode": "xml"},
        )


# ---------------------------------------------------------------------------
# GEO
# ---------------------------------------------------------------------------

# Curated critical-illness series with per-sample outcome annotation. Listed
# explicitly because GEO's free-text search returns mostly unlabelled series,
# and a cohort without outcomes is useless for validation.
CURATED_GEO_SERIES: Dict[str, str] = {
    "GSE65682": "Sepsis / CAP ICU patients, 28-day mortality (MARS cohort)",
    "GSE63042": "Sepsis survivors vs non-survivors, whole blood",
    "GSE54514": "Sepsis ICU, daily sampling, survival outcome",
    "GSE10474": "Sepsis-induced ARDS, 28-day mortality",
    "GSE33341": "Sepsis vs uninfected critically ill controls",
    "GSE28750": "Sepsis, post-surgical and healthy controls",
    "GSE95233": "Septic shock, survivors vs non-survivors",
    "GSE57065": "Septic shock time course",
}

# Sample-characteristic keys that carry a deterioration outcome. GEO submitters
# use inconsistent labels, so matching is by substring over a known set.
OUTCOME_KEYS = (
    "mortality", "survival", "outcome", "died", "death", "survivor",
    "28-day", "28 day", "day28", "hospital_outcome", "vital status",
)

SEVERITY_KEYS = (
    "sofa", "apache", "severity", "septic shock", "sepsis", "organ failure",
    "shock", "icu", "disease state", "group", "condition",
)


@dataclass
class GEOSeries:
    """A parsed GEO series: per-sample phenotype plus optional expression."""

    accession: str
    title: str = ""
    n_samples: int = 0
    phenotype: pd.DataFrame = field(default_factory=pd.DataFrame)
    expression: Optional[pd.DataFrame] = None

    def __repr__(self) -> str:
        return (
            f"GEOSeries({self.accession}, n={self.n_samples}, "
            f"columns={list(self.phenotype.columns)[:6]})"
        )


class GEOLoader:
    """Downloads and parses GEO series matrix files."""

    def __init__(
        self,
        client: Optional[NCBIClient] = None,
        cache_dir: str | Path = "data/raw/geo",
        timeout: int = 300,
    ):
        self.client = client or NCBIClient()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout

    def search_series(self, term: str, retmax: int = 50) -> pd.DataFrame:
        """Search GEO DataSets for series matching a query."""
        uids = self.client.esearch("gds", term, retmax=retmax)
        summaries = self.client.esummary("gds", uids)

        rows = []
        for summary in summaries:
            rows.append(
                {
                    "accession": summary.get("accession", ""),
                    "title": summary.get("title", ""),
                    "n_samples": int(summary.get("n_samples", 0) or 0),
                    "gdstype": summary.get("gdsType", ""),
                    "taxon": summary.get("taxon", ""),
                    "pubmed_ids": summary.get("pubmedids", []),
                }
            )
        return pd.DataFrame(rows)

    def _series_matrix_url(self, accession: str) -> str:
        # GEO buckets series into directories by truncating the last 3 digits:
        # GSE65682 -> GSE65nnn.
        stub = accession[:-3] + "nnn"
        return (
            f"{GEO_FTP_BASE}/{stub}/{accession}/matrix/"
            f"{accession}_series_matrix.txt.gz"
        )

    def _download_series_matrix(self, accession: str) -> Path:
        local = self.cache_dir / f"{accession}_series_matrix.txt.gz"
        if local.exists():
            return local

        url = self._series_matrix_url(accession)
        logger.info("Downloading %s", url)
        request = urllib.request.Request(url, headers={"User-Agent": self.client.tool})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            local.write_bytes(response.read())
        return local

    def load_series(
        self, accession: str, include_expression: bool = False
    ) -> GEOSeries:
        """Parse a series matrix into phenotype (and optionally expression).

        Expression matrices run to hundreds of MB; they are skipped unless
        asked for, since the phenotype table is what carries the outcomes.
        """
        path = self._download_series_matrix(accession)

        title = ""
        sample_ids: List[str] = []
        characteristics: List[List[str]] = []
        sample_fields: Dict[str, List[str]] = {}
        expression_rows: List[List[str]] = []
        expression_header: List[str] = []
        in_matrix = False

        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.rstrip("\n")

                if line.startswith("!series_matrix_table_begin"):
                    in_matrix = True
                    continue
                if line.startswith("!series_matrix_table_end"):
                    in_matrix = False
                    continue

                if in_matrix:
                    if not include_expression:
                        continue
                    fields = [f.strip('"') for f in line.split("\t")]
                    if not expression_header:
                        expression_header = fields
                    else:
                        expression_rows.append(fields)
                    continue

                if not line.startswith("!"):
                    continue

                key, _, raw = line.partition("\t")
                values = [v.strip('"') for v in raw.split("\t")] if raw else []

                if key == "!Series_title" and values:
                    title = values[0]
                elif key == "!Sample_geo_accession":
                    sample_ids = values
                elif key.startswith("!Sample_characteristics"):
                    characteristics.append(values)
                elif key in ("!Sample_title", "!Sample_source_name_ch1"):
                    sample_fields[key.replace("!Sample_", "")] = values

        phenotype = self._build_phenotype(sample_ids, characteristics, sample_fields)

        expression = None
        if include_expression and expression_rows:
            expression = pd.DataFrame(expression_rows, columns=expression_header)
            expression = expression.set_index(expression.columns[0])
            expression = expression.apply(pd.to_numeric, errors="coerce")

        return GEOSeries(
            accession=accession,
            title=title,
            n_samples=len(sample_ids),
            phenotype=phenotype,
            expression=expression,
        )

    @staticmethod
    def _build_phenotype(
        sample_ids: Sequence[str],
        characteristics: Sequence[Sequence[str]],
        extra_fields: Dict[str, Sequence[str]],
    ) -> pd.DataFrame:
        """Turn GEO's ragged "key: value" characteristic lines into columns.

        Each !Sample_characteristics line holds one attribute across all
        samples, formatted "label: value" — but submitters reorder attributes
        between samples, so the label must be read per cell, not per line.
        """
        if not sample_ids:
            return pd.DataFrame()

        records: List[Dict[str, str]] = [
            {"sample_id": sample_id} for sample_id in sample_ids
        ]

        for line_values in characteristics:
            for index, cell in enumerate(line_values):
                if index >= len(records) or not cell:
                    continue
                label, sep, value = cell.partition(":")
                if not sep:
                    continue
                column = label.strip().lower().replace(" ", "_")
                if column:
                    records[index][column] = value.strip()

        for field_name, values in extra_fields.items():
            for index, value in enumerate(values):
                if index < len(records):
                    records[index][field_name] = value

        return pd.DataFrame(records)

    def extract_outcome(self, series: GEOSeries) -> pd.DataFrame:
        """Derive a binary deterioration label from phenotype annotations.

        Returns the phenotype with `deteriorated` added where an outcome column
        could be identified; the column is absent when none could be, rather
        than being guessed.
        """
        phenotype = series.phenotype.copy()
        if phenotype.empty:
            return phenotype

        outcome_col = next(
            (
                col
                for col in phenotype.columns
                if any(key in col.lower() for key in OUTCOME_KEYS)
            ),
            None,
        )
        if outcome_col is None:
            logger.warning(
                "%s: no outcome column found among %s",
                series.accession,
                list(phenotype.columns),
            )
            return phenotype

        values = phenotype[outcome_col].fillna("").astype(str).str.strip().str.lower()

        died_tokens = {"1", "yes", "y", "died", "death", "nonsurvivor",
                       "non-survivor", "non survivor", "dead", "deceased",
                       "expired", "true"}
        survived_tokens = {"0", "no", "n", "survivor", "survived", "alive",
                           "living", "false"}

        label = pd.Series(np.nan, index=phenotype.index, dtype="float64")
        label[values.isin(died_tokens)] = 1.0
        label[values.isin(survived_tokens)] = 0.0

        # Substring fallback for free-text like "28-day mortality: non-survivor".
        unresolved = label.isna()
        if unresolved.any():
            text = values[unresolved]
            label.loc[unresolved & values.str.contains("non-?survivor|died|death|dead|expired", regex=True)] = 1.0
            label.loc[unresolved & values.str.contains("survivor|alive|discharged", regex=True) & ~values.str.contains("non-?survivor", regex=True)] = 0.0

        resolved = label.notna().sum()
        logger.info(
            "%s: resolved outcome for %d/%d samples from column %r",
            series.accession,
            resolved,
            len(phenotype),
            outcome_col,
        )

        phenotype["outcome_source_column"] = outcome_col
        phenotype["deteriorated"] = label
        return phenotype

    def load_curated_cohorts(
        self, accessions: Optional[Sequence[str]] = None
    ) -> pd.DataFrame:
        """Load the curated critical-illness series into one phenotype table."""
        accessions = list(accessions or CURATED_GEO_SERIES)
        frames = []

        for accession in accessions:
            try:
                series = self.load_series(accession)
                phenotype = self.extract_outcome(series)
            except Exception as exc:
                logger.warning("Skipping %s: %s", accession, exc)
                continue

            if phenotype.empty:
                continue
            phenotype = phenotype.copy()
            phenotype["series"] = accession
            phenotype["series_title"] = series.title
            frames.append(phenotype)

        if not frames:
            raise ValueError("No GEO series could be loaded.")

        pooled = pd.concat(frames, ignore_index=True, sort=False)
        logger.info(
            "Loaded %d samples across %d GEO series", len(pooled), len(frames)
        )
        return pooled


# ---------------------------------------------------------------------------
# PubMed / MeSH
# ---------------------------------------------------------------------------

class MeSHLexiconBuilder:
    """Expands clinical concept synonyms from the MeSH vocabulary.

    A hand-written lexicon lists "myocardial infarction" and forgets "MI",
    "heart attack" and "STEMI". MeSH entry terms are exactly that synonym set,
    maintained by the NLM, so the lexicon can be grown from the source instead
    of by guesswork.
    """

    def __init__(self, client: Optional[NCBIClient] = None):
        self.client = client or NCBIClient()

    def fetch_entry_terms(self, concept: str, max_terms: int = 40) -> List[str]:
        """Return MeSH entry terms (synonyms) for a concept name."""
        uids = self.client.esearch("mesh", f"{concept}[MeSH Terms]", retmax=3)
        if not uids:
            uids = self.client.esearch("mesh", concept, retmax=3)
        if not uids:
            logger.info("No MeSH record for %r", concept)
            return []

        summaries = self.client.esummary("mesh", uids)
        terms: List[str] = []
        for summary in summaries:
            for key in ("ds_meshterms", "ds_meshsynonyms", "ds_scopenote"):
                value = summary.get(key)
                if isinstance(value, list):
                    terms.extend(str(v) for v in value)

        normalized: List[str] = []
        seen = set()
        for term in terms:
            cleaned = term.strip().lower()
            # MeSH inverts headings for alphabetization ("Infarction, Myocardial");
            # the inverted form never appears in prose, so restore the order.
            if "," in cleaned:
                head, _, tail = cleaned.partition(",")
                cleaned = f"{tail.strip()} {head.strip()}".strip()
            if cleaned and cleaned not in seen and len(cleaned) > 2:
                seen.add(cleaned)
                normalized.append(cleaned)

        return normalized[:max_terms]

    def expand_lexicon(
        self, concepts: Dict[str, Sequence[str]], max_terms: int = 40
    ) -> Dict[str, List[str]]:
        """Add MeSH synonyms to an existing {concept: patterns} mapping."""
        expanded: Dict[str, List[str]] = {}

        for name, patterns in concepts.items():
            merged = list(patterns)
            seen = {p.lower() for p in patterns}
            # Query on the longest pattern; it is the most specific and least
            # likely to resolve to an unrelated heading.
            query = max(patterns, key=len) if patterns else name.replace("_", " ")
            try:
                for term in self.fetch_entry_terms(query, max_terms=max_terms):
                    if term not in seen:
                        seen.add(term)
                        merged.append(term)
            except Exception as exc:
                logger.warning("MeSH expansion failed for %s: %s", name, exc)

            expanded[name] = merged

        return expanded

    def save(self, lexicon: Dict[str, List[str]], path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(lexicon, indent=2, ensure_ascii=False))
        logger.info("Wrote expanded lexicon to %s", path)

    @staticmethod
    def load(path: str | Path) -> Dict[str, List[str]]:
        return json.loads(Path(path).read_text())


def expand_concept_lexicon(
    output_path: str | Path = "data/processed/mesh_lexicon.json",
    client: Optional[NCBIClient] = None,
) -> Dict[str, List[str]]:
    """Expand the built-in clinical lexicon with MeSH synonyms and save it."""
    from features.clinical_nlp import CONCEPT_LEXICON

    builder = MeSHLexiconBuilder(client)
    base = {concept.name: list(concept.patterns) for concept in CONCEPT_LEXICON}
    expanded = builder.expand_lexicon(base)
    builder.save(expanded, output_path)
    return expanded


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    loader = GEOLoader()
    print("Curated critical-illness series:")
    for accession, description in CURATED_GEO_SERIES.items():
        print(f"  {accession}: {description}")

    series = loader.load_series("GSE65682")
    print(f"\n{series}")
    print(loader.extract_outcome(series).head())
