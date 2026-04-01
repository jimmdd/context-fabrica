from __future__ import annotations

import re
from collections import Counter

TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")
STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "over",
    "when",
    "your",
    "will",
    "they",
    "have",
    "has",
    "are",
    "not",
    "but",
    "use",
    "can",
    "any",
    "all",
}


def tokenize(text: str) -> list[str]:
    tokens = [m.group(0).lower() for m in TOKEN_RE.finditer(text)]
    return [tok for tok in tokens if tok not in STOP_WORDS]


def extract_entities(text: str, max_entities: int = 12) -> list[str]:
    raw = [m.group(0) for m in TOKEN_RE.finditer(text)]
    candidates = []
    for token in raw:
        if token.lower() in STOP_WORDS:
            continue
        if token[0].isupper() or "_" in token or any(ch.isdigit() for ch in token):
            candidates.append(token.lower())
    if not candidates:
        freq = Counter(tokenize(text))
        return [t for t, _ in freq.most_common(max_entities)]
    freq = Counter(candidates)
    return [t for t, _ in freq.most_common(max_entities)]


def extract_relations(text: str, entities: list[str]) -> list[tuple[str, str, str]]:
    relations: list[tuple[str, str, str]] = []
    if len(entities) < 2:
        return relations
    windows = [line.strip().lower() for line in text.splitlines() if line.strip()]
    for line in windows:
        present = [e for e in entities if e in line]
        if len(present) < 2:
            continue
        for idx in range(len(present) - 1):
            left = present[idx]
            right = present[idx + 1]
            relation = "related_to"
            if "depends on" in line or "depend" in line:
                relation = "depends_on"
            elif "calls" in line or "uses" in line:
                relation = "uses"
            elif "owns" in line:
                relation = "owns"
            elif "implements" in line:
                relation = "implements"
            relations.append((left, relation, right))
    return relations
