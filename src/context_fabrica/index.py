from __future__ import annotations

import math
from collections import Counter, defaultdict

from .entity import tokenize


class LexicalSemanticIndex:
    def __init__(self) -> None:
        self._doc_terms: dict[str, Counter[str]] = {}
        self._doc_lengths: dict[str, int] = {}
        self._term_doc_freq: Counter[str] = Counter()
        self._avg_doc_len = 0.0

    def upsert(self, record_id: str, text: str) -> None:
        if record_id in self._doc_terms:
            old_terms = self._doc_terms[record_id]
            for term in old_terms:
                self._term_doc_freq[term] -= 1
                if self._term_doc_freq[term] <= 0:
                    del self._term_doc_freq[term]

        terms = Counter(tokenize(text))
        self._doc_terms[record_id] = terms
        self._doc_lengths[record_id] = sum(terms.values())
        for term in terms:
            self._term_doc_freq[term] += 1

        total = sum(self._doc_lengths.values())
        count = max(len(self._doc_lengths), 1)
        self._avg_doc_len = total / count

    def score(self, query: str, k1: float = 1.2, b: float = 0.75) -> dict[str, float]:
        query_terms = tokenize(query)
        if not query_terms:
            return {}

        n_docs = max(len(self._doc_terms), 1)
        scores: dict[str, float] = defaultdict(float)

        for term in query_terms:
            df = self._term_doc_freq.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            for record_id, term_freqs in self._doc_terms.items():
                tf = term_freqs.get(term, 0)
                if tf == 0:
                    continue
                doc_len = self._doc_lengths.get(record_id, 1)
                denom = tf + k1 * (1 - b + b * doc_len / max(self._avg_doc_len, 1.0))
                scores[record_id] += idf * ((tf * (k1 + 1)) / denom)

        return scores
