from __future__ import annotations

import re

from .models import KnowledgeRecord

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")


class TokenOverlapReranker:
    """Deterministic low-cost reranker for exact-term alignment.

    This is intentionally simple and dependency-free. It is useful as an
    opt-in second-stage reranker in environments where cross-encoders are
    not available yet.
    """

    def score(self, query: str, record: KnowledgeRecord) -> float:
        query_tokens = set(TOKEN_PATTERN.findall(query.lower()))
        record_tokens = set(TOKEN_PATTERN.findall(record.text.lower()))
        if not query_tokens or not record_tokens:
            return 0.0
        overlap = query_tokens & record_tokens
        jaccard = len(overlap) / len(query_tokens | record_tokens)
        coverage = len(overlap) / len(query_tokens)
        phrase_bonus = 0.15 if query.lower() in record.text.lower() else 0.0
        return min((0.45 * jaccard) + (0.55 * coverage) + phrase_bonus, 1.0)
