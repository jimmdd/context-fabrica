from __future__ import annotations

from collections import Counter
from uuid import uuid4

from .entity import extract_entities
from .models import KnowledgeRecord


def build_observation_record(
    records: list[KnowledgeRecord],
    *,
    record_id: str | None = None,
    source: str = "observation-synthesizer",
    max_sentences: int = 3,
) -> KnowledgeRecord:
    if not records:
        raise ValueError("At least one record is required to synthesize an observation")

    unique_sentences = _collect_sentences(records, limit=max_sentences)
    common_entities = _common_entities(records)
    domains = {record.domain for record in records}
    namespaces = {record.namespace for record in records}
    confidence = sum(record.confidence for record in records) / len(records)

    prefix = "Synthesized observation"
    if common_entities:
        prefix += f" about {', '.join(common_entities[:3])}"
    text = f"{prefix}: {' '.join(unique_sentences)}"

    metadata = {
        "derived_from": [record.record_id for record in records],
        "derived_from_count": len(records),
        "source_types": sorted({record.source for record in records}),
        "common_entities": common_entities,
        "synthesis_strategy": "deterministic_sentence_merge",
    }

    occurred_points = [record.occurred_from for record in records if record.occurred_from is not None]
    occurred_ends = [record.occurred_to or record.occurred_from for record in records if record.occurred_from is not None]

    return KnowledgeRecord(
        record_id=record_id or str(uuid4()),
        text=text,
        source=source,
        domain=domains.pop() if len(domains) == 1 else "global",
        namespace=namespaces.pop() if len(namespaces) == 1 else "default",
        confidence=min(confidence, 0.95),
        tags=["observation"],
        metadata=metadata,
        stage="canonical",
        kind="observation",
        occurred_from=min(occurred_points) if occurred_points else None,
        occurred_to=max(occurred_ends) if occurred_ends else None,
    )


def _collect_sentences(records: list[KnowledgeRecord], *, limit: int) -> list[str]:
    sentences: list[str] = []
    seen: set[str] = set()
    for record in records:
        for raw_sentence in record.text.replace("\n", " ").split("."):
            sentence = raw_sentence.strip()
            if not sentence:
                continue
            normalized = sentence.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            sentences.append(sentence if sentence.endswith(".") else f"{sentence}.")
            if len(sentences) >= limit:
                return sentences
    if not sentences:
        return ["No stable facts were available to synthesize."]
    return sentences


def _common_entities(records: list[KnowledgeRecord]) -> list[str]:
    counts: Counter[str] = Counter()
    for record in records:
        counts.update(set(extract_entities(record.text)))
    return [entity for entity, count in counts.most_common() if count > 1]
