"""English Wikipedia as a source of clinical *terminology*.

Scope, stated plainly: Wikipedia is used here to expand the synonym sets in the
clinical NLP lexicon, and for nothing else. It is not a clinical authority, and
this module deliberately does **not** import reference ranges, thresholds, dosing
or diagnostic criteria from it. Those come from LOINC and the reference ranges
already encoded in `features/lab_features.py`, which are traceable to laboratory
standards. An anonymously editable page is a fine place to learn that people
write "heart attack" for myocardial infarction; it is not a place to learn what
counts as a critical potassium.

What it is genuinely good at is redirects. Wikipedia's redirect graph is a
large, human-curated synonym list: `Heart attack`, `MI (heart)`, `Myocardial
infarct` and dozens more all point at one article. That is exactly the mapping a
hand-written lexicon keeps missing, and it complements MeSH — MeSH gives formal
indexing vocabulary, Wikipedia gives what clinicians and patients actually type.

API: the MediaWiki Action API at https://en.wikipedia.org/w/api.php. No key is
needed; the etiquette requirement is a descriptive User-Agent and modest
concurrency. Responses are cached on disk.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

logger = logging.getLogger(__name__)

API = "https://en.wikipedia.org/w/api.php"

# Wikipedia asks for a User-Agent identifying the tool and a contact.
USER_AGENT = (
    "PenuX-II/0.1 (clinical NLP lexicon expansion; "
    "https://github.com/netanelcyber/penux)"
)

# Titles matching these are redirects that add noise rather than clinical
# synonyms: disambiguation scaffolding, list pages, and category stubs.
_NOISE_PATTERNS = (
    re.compile(r"\(disambiguation\)", re.I),
    re.compile(r"^list of ", re.I),
    re.compile(r"^index of ", re.I),
    re.compile(r"^outline of ", re.I),
    re.compile(r"^(category|template|portal|wikipedia|help|draft):", re.I),
)


class WikipediaClient:
    """Cached, rate-limited MediaWiki Action API client."""

    def __init__(
        self,
        cache_dir: str | Path = "data/raw/wikipedia_cache",
        requests_per_second: float = 5.0,
        timeout: int = 30,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = 1.0 / requests_per_second
        self.timeout = timeout
        self._last_request = 0.0

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()

    def get(self, params: Dict[str, str], use_cache: bool = True) -> Dict:
        query = {**params, "format": "json", "formatversion": "2"}
        encoded = urllib.parse.urlencode(query)

        cache_path = self.cache_dir / (
            hashlib.sha256(encoded.encode()).hexdigest()[:32] + ".json"
        )
        if use_cache and cache_path.exists():
            return json.loads(cache_path.read_text())

        self._wait()
        request = urllib.request.Request(
            f"{API}?{encoded}", headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read())

        if use_cache:
            cache_path.write_text(json.dumps(payload))
        return payload

    def resolve_title(self, term: str) -> Optional[str]:
        """Resolve a search term to a canonical article title.

        Search is used rather than a direct title lookup because clinical terms
        rarely match an article title exactly, and a wrong exact-match guess
        fails silently where a search at least returns the nearest article.
        """
        payload = self.get(
            {
                "action": "query",
                "list": "search",
                "srsearch": term,
                "srlimit": "1",
                "srnamespace": "0",
            }
        )
        results = payload.get("query", {}).get("search", [])
        return results[0]["title"] if results else None

    def redirects_to(self, title: str, limit: int = 200) -> List[str]:
        """Titles that redirect to this article — the synonym set."""
        payload = self.get(
            {
                "action": "query",
                "titles": title,
                "prop": "redirects",
                "rdlimit": str(limit),
                "rdnamespace": "0",
            }
        )
        pages = payload.get("query", {}).get("pages", [])
        if not pages:
            return []
        return [r["title"] for r in pages[0].get("redirects", [])]

    def summary(self, title: str) -> str:
        """The article's lead extract, as plain text."""
        payload = self.get(
            {
                "action": "query",
                "titles": title,
                "prop": "extracts",
                "exintro": "1",
                "explaintext": "1",
            }
        )
        pages = payload.get("query", {}).get("pages", [])
        return pages[0].get("extract", "") if pages else ""


@dataclass
class ConceptSynonyms:
    """Synonyms gathered for one clinical concept."""

    concept: str
    article: Optional[str]
    surface_forms: List[str] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"ConceptSynonyms({self.concept}, article={self.article!r}, "
            f"+{len(self.surface_forms)} forms)"
        )


class WikipediaLexiconExpander:
    """Grows the clinical concept lexicon from Wikipedia redirects."""

    def __init__(
        self,
        client: Optional[WikipediaClient] = None,
        min_length: int = 3,
        max_words: int = 5,
    ):
        """
        Args:
            min_length: shortest acceptable surface form. Two-character forms
                are almost all false positives against clinical prose.
            max_words: longest acceptable form. Long redirect titles are
                descriptive sentences, not terms a clinician writes.
        """
        self.client = client or WikipediaClient()
        self.min_length = min_length
        self.max_words = max_words

    def _acceptable(self, candidate: str) -> bool:
        if len(candidate) < self.min_length:
            return False
        if len(candidate.split()) > self.max_words:
            return False
        if any(pattern.search(candidate) for pattern in _NOISE_PATTERNS):
            return False
        # A form that is mostly punctuation or digits will not match prose and
        # would only widen the regex for nothing.
        letters = sum(character.isalpha() for character in candidate)
        return letters >= max(2, len(candidate) // 2)

    def expand_concept(self, concept: str, seed_term: str) -> ConceptSynonyms:
        """Collect acceptable surface forms for one concept."""
        try:
            article = self.client.resolve_title(seed_term)
        except Exception as exc:
            logger.warning("Wikipedia lookup failed for %r: %s", seed_term, exc)
            return ConceptSynonyms(concept=concept, article=None)

        if article is None:
            return ConceptSynonyms(concept=concept, article=None)

        try:
            candidates = [article] + self.client.redirects_to(article)
        except Exception as exc:
            logger.warning("Redirect lookup failed for %r: %s", article, exc)
            candidates = [article]

        accepted: List[str] = []
        rejected: List[str] = []
        seen: Set[str] = set()

        for candidate in candidates:
            normalized = candidate.strip().lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            (accepted if self._acceptable(normalized) else rejected).append(normalized)

        return ConceptSynonyms(
            concept=concept, article=article, surface_forms=accepted, rejected=rejected
        )

    def expand_lexicon(
        self, concepts: Optional[Dict[str, Sequence[str]]] = None
    ) -> Dict[str, List[str]]:
        """Merge Wikipedia surface forms into the built-in concept lexicon.

        Existing hand-written patterns are always kept: they were chosen for a
        clinical reason, and an automated source should widen the net rather
        than replace curated judgement.
        """
        if concepts is None:
            from features.clinical_nlp import CONCEPT_LEXICON

            concepts = {c.name: list(c.patterns) for c in CONCEPT_LEXICON}

        expanded: Dict[str, List[str]] = {}
        for name, patterns in concepts.items():
            merged = list(patterns)
            seen = {p.lower() for p in patterns}

            # Seed on the longest pattern: it is the most specific, and a short
            # one like "shock" resolves to an unrelated article.
            seed = max(patterns, key=len) if patterns else name.replace("_", " ")
            result = self.expand_concept(name, seed)

            for form in result.surface_forms:
                if form not in seen:
                    seen.add(form)
                    merged.append(form)

            expanded[name] = merged
            logger.info(
                "%s: %d -> %d forms (article: %s)",
                name, len(patterns), len(merged), result.article,
            )

        return expanded

    def save(self, lexicon: Dict[str, List[str]], path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(lexicon, indent=2, ensure_ascii=False))
        logger.info("Wrote %s", path)


def merge_lexicons(*sources: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Union several expanded lexicons (Wikipedia, MeSH, hand-written).

    The sources are complementary: MeSH supplies formal indexing vocabulary,
    Wikipedia supplies what people actually write. Neither alone is enough.
    """
    merged: Dict[str, List[str]] = {}
    for source in sources:
        for concept, patterns in source.items():
            existing = merged.setdefault(concept, [])
            seen = {p.lower() for p in existing}
            for pattern in patterns:
                if pattern.lower() not in seen:
                    seen.add(pattern.lower())
                    existing.append(pattern)
    return merged


def build_expanded_lexicon(
    output_path: str | Path = "data/processed/expanded_lexicon.json",
    include_mesh: bool = True,
) -> Dict[str, List[str]]:
    """Expand the lexicon from Wikipedia, and from MeSH when reachable."""
    expander = WikipediaLexiconExpander()
    wikipedia = expander.expand_lexicon()
    sources = [wikipedia]

    if include_mesh:
        try:
            from data.ncbi import MeSHLexiconBuilder
            from features.clinical_nlp import CONCEPT_LEXICON

            base = {c.name: list(c.patterns) for c in CONCEPT_LEXICON}
            sources.append(MeSHLexiconBuilder().expand_lexicon(base))
        except Exception as exc:
            logger.warning("MeSH expansion unavailable: %s", exc)

    merged = merge_lexicons(*sources)
    expander.save(merged, output_path)
    return merged


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    expander = WikipediaLexiconExpander()
    for concept, seed in [
        ("myocardial_infarction", "myocardial infarction"),
        ("sepsis", "sepsis"),
        ("renal_failure", "acute kidney injury"),
    ]:
        result = expander.expand_concept(concept, seed)
        print(f"\n{result}")
        for form in result.surface_forms[:12]:
            print(f"  · {form}")
