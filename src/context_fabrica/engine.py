from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from .entity import extract_entities, extract_relations
from .graph import KnowledgeGraph
from .index import LexicalSemanticIndex
from .models import KnowledgeRecord, QueryResult, Relation
from .policy import decide_memory_tier, promote_record


class DomainMemoryEngine:
    def __init__(self) -> None:
        self._records: dict[str, KnowledgeRecord] = {}
        self._index = LexicalSemanticIndex()
        self._graph = KnowledgeGraph()
        self._weights = {
            "semantic": 0.50,
            "graph": 0.30,
            "recency": 0.12,
            "confidence": 0.08,
        }

    @property
    def records(self) -> dict[str, KnowledgeRecord]:
        return self._records

    def ingest(
        self,
        text: str,
        *,
        source: str = "unknown",
        domain: str = "global",
        confidence: float = 0.6,
        tags: Iterable[str] | None = None,
        metadata: dict[str, object] | None = None,
        record_id: str | None = None,
        auto_stage: bool = True,
    ) -> KnowledgeRecord:
        rid = record_id or str(uuid4())
        record = KnowledgeRecord(
            record_id=rid,
            text=text,
            source=source,
            domain=domain,
            confidence=max(0.0, min(1.0, confidence)),
            tags=list(tags or []),
            metadata=dict(metadata or {}),
        )
        if auto_stage:
            decision = decide_memory_tier(record)
            record.stage = decision.stage
            record.kind = decision.kind
            record.metadata.setdefault("promotion_rationale", decision.rationale)
        self._records[rid] = record
        self._index.upsert(rid, text)

        entities = extract_entities(text)
        self._graph.attach_record_entities(rid, entities)
        for left, rel, right in extract_relations(text, entities):
            self._graph.add_relation(Relation(left, rel, right, weight=1.0))

        return record

    def query(
        self,
        prompt: str,
        *,
        top_k: int = 5,
        hops: int = 2,
        domain: str | None = None,
        now: datetime | None = None,
        as_of: datetime | None = None,
        include_staged: bool = False,
    ) -> list[QueryResult]:
        ref_now = now or datetime.now(tz=timezone.utc)
        point_in_time = as_of or ref_now

        semantic = self._index.score(prompt)
        query_entities = extract_entities(prompt)
        graph = self._graph.records_for_entities(query_entities, hops=hops)

        all_ids = set(semantic) | set(graph)
        if domain:
            all_ids = {rid for rid in all_ids if self._records[rid].domain == domain}
        all_ids = {rid for rid in all_ids if self._is_valid(self._records[rid], point_in_time)}
        if not include_staged:
            all_ids = {rid for rid in all_ids if self._records[rid].stage != "staged"}

        sem_max = max(semantic.values(), default=1.0)
        graph_max = max(graph.values(), default=1.0)

        ranked: list[QueryResult] = []
        for rid in all_ids:
            record = self._records[rid]
            sem_norm = semantic.get(rid, 0.0) / sem_max
            graph_norm = graph.get(rid, 0.0) / graph_max

            age_hours = max((ref_now - record.created_at).total_seconds() / 3600.0, 0.0)
            recency_score = 1.0 / (1.0 + age_hours / 24.0)
            confidence_score = record.confidence

            final_score = (
                self._weights["semantic"] * sem_norm
                + self._weights["graph"] * graph_norm
                + self._weights["recency"] * recency_score
                + self._weights["confidence"] * confidence_score
            )

            rationale: list[str] = []
            if sem_norm > 0.0:
                rationale.append("semantic_match")
            if graph_norm > 0.0:
                rationale.append("graph_relation")
            if recency_score > 0.5:
                rationale.append("recent")
            if confidence_score > 0.7:
                rationale.append("high_confidence")

            ranked.append(
                QueryResult(
                    record=record,
                    score=final_score,
                    semantic_score=sem_norm,
                    graph_score=graph_norm,
                    recency_score=recency_score,
                    confidence_score=confidence_score,
                    rationale=rationale,
                )
            )

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:top_k]

    def related_records(self, record_id: str, hops: int = 1, top_k: int = 8) -> list[KnowledgeRecord]:
        entities = list(self._graph.record_entities(record_id))
        if not entities:
            return []
        scores = self._graph.records_for_entities(entities, hops=hops)
        ranked_ids = [rid for rid, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True) if rid != record_id]
        return [self._records[rid] for rid in ranked_ids[:top_k] if self._is_valid(self._records[rid], datetime.now(tz=timezone.utc))]

    def invalidate_record(
        self,
        record_id: str,
        *,
        invalidated_at: datetime | None = None,
        reason: str = "superseded",
    ) -> None:
        record = self._records[record_id]
        record.valid_to = invalidated_at or datetime.now(tz=timezone.utc)
        record.metadata["invalid_reason"] = reason

    def promote_record(self, record_id: str, *, reviewed_at: datetime | None = None) -> KnowledgeRecord:
        return promote_record(self._records[record_id], reviewed_at=reviewed_at)

    def _is_valid(self, record: KnowledgeRecord, at: datetime) -> bool:
        if at < record.valid_from:
            return False
        if record.valid_to is not None and at > record.valid_to:
            return False
        return True
