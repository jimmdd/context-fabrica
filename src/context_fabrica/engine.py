from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import sqrt
from typing import Iterable, Literal
from uuid import uuid4

from .config import ScoringWeights
from .embedding import Embedder, HashEmbedder
from .entity import extract_entities, extract_relations
from .graph import KnowledgeGraph
from .index import LexicalSemanticIndex
from .models import KnowledgeRecord, QueryResult, Relation
from .policy import decide_memory_tier, promote_record

ScoringMode = Literal["hybrid", "embedding", "bm25", "rrf"]


class DomainMemoryEngine:
    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
        scoring: ScoringMode = "hybrid",
        weights: ScoringWeights | None = None,
    ) -> None:
        self._records: dict[str, KnowledgeRecord] = {}
        self._index = LexicalSemanticIndex()
        self._graph = KnowledgeGraph()
        self._embedder = embedder or HashEmbedder()
        self._embeddings: dict[str, list[float]] = {}
        self._scoring = scoring
        self._scoring_weights = weights or ScoringWeights()
        self._weights = {
            "semantic": self._scoring_weights.semantic,
            "graph": self._scoring_weights.graph,
            "recency": self._scoring_weights.recency,
            "confidence": self._scoring_weights.confidence,
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
        entities: list[str] | None = None,
        relations: list[Relation] | None = None,
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
        self._embeddings[rid] = self._embedder.embed(text)

        resolved_entities = entities if entities is not None else extract_entities(text)
        self._graph.attach_record_entities(rid, resolved_entities)

        if relations is not None:
            for rel in relations:
                self._graph.add_relation(rel)
        else:
            for left, rel_type, right in extract_relations(text, resolved_entities):
                self._graph.add_relation(Relation(left, rel_type, right, weight=1.0))

        return record

    def query(
        self,
        prompt: str,
        *,
        top_k: int = 5,
        hops: int = 2,
        domain: str | None = None,
        namespace: str | None = None,
        now: datetime | None = None,
        as_of: datetime | None = None,
        include_staged: bool = False,
    ) -> list[QueryResult]:
        ref_now = now or datetime.now(tz=timezone.utc)
        point_in_time = as_of or ref_now

        bm25_scores = self._index.score(prompt)
        embedding_scores = self._embedding_scores(prompt) if self._scoring != "bm25" else {}
        query_entities = extract_entities(prompt)
        graph = self._graph.records_for_entities(query_entities, hops=hops)

        all_ids = set(bm25_scores) | set(embedding_scores) | set(graph)
        if domain:
            all_ids = {rid for rid in all_ids if self._records[rid].domain == domain}
        if namespace:
            all_ids = {rid for rid in all_ids if self._records[rid].namespace == namespace}
        all_ids = {rid for rid in all_ids if self._is_valid(self._records[rid], point_in_time)}
        if not include_staged:
            all_ids = {rid for rid in all_ids if self._records[rid].stage != "staged"}

        semantic = self._fuse_semantic(bm25_scores, embedding_scores, all_ids)

        if self._scoring == "rrf":
            return self._score_rrf(all_ids, semantic, graph, ref_now, top_k)

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

    def supersede_record(
        self,
        old_record_id: str,
        new_text: str,
        *,
        source: str = "unknown",
        domain: str | None = None,
        confidence: float | None = None,
        record_id: str | None = None,
        reason: str = "updated",
        entities: list[str] | None = None,
        relations: list[Relation] | None = None,
    ) -> KnowledgeRecord:
        """Replace an old record with a new one, linking via supersedes."""
        old = self._records[old_record_id]
        self.invalidate_record(old_record_id, reason=reason)
        new = self.ingest(
            new_text,
            source=source or old.source,
            domain=domain or old.domain,
            confidence=confidence if confidence is not None else old.confidence,
            tags=list(old.tags),
            metadata={**old.metadata, "supersession_reason": reason},
            record_id=record_id,
            entities=entities,
            relations=relations,
        )
        new.supersedes = old_record_id
        new.namespace = old.namespace
        return new

    def supersession_chain(self, record_id: str) -> list[KnowledgeRecord]:
        """Walk the supersession chain backward from a record to its origin."""
        chain: list[KnowledgeRecord] = []
        current = self._records.get(record_id)
        seen: set[str] = set()
        while current and current.record_id not in seen:
            chain.append(current)
            seen.add(current.record_id)
            if current.supersedes and current.supersedes in self._records:
                current = self._records[current.supersedes]
            else:
                break
        return chain

    def promote_record(self, record_id: str, *, reviewed_at: datetime | None = None) -> KnowledgeRecord:
        return promote_record(self._records[record_id], reviewed_at=reviewed_at)

    def _is_valid(self, record: KnowledgeRecord, at: datetime) -> bool:
        if at < record.valid_from:
            return False
        if record.valid_to is not None and at > record.valid_to:
            return False
        return True

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sqrt(sum(x * x for x in a)) or 1.0
        norm_b = sqrt(sum(x * x for x in b)) or 1.0
        return max(dot / (norm_a * norm_b), 0.0)

    def _embedding_scores(self, prompt: str) -> dict[str, float]:
        query_vec = self._embedder.embed(prompt)
        scores: dict[str, float] = {}
        for rid, vec in self._embeddings.items():
            sim = self._cosine_similarity(query_vec, vec)
            if sim > 0.0:
                scores[rid] = sim
        return scores

    def _score_rrf(
        self,
        candidates: set[str],
        semantic: dict[str, float],
        graph: dict[str, float],
        ref_now: datetime,
        top_k: int,
        k: int = 60,
    ) -> list[QueryResult]:
        """Reciprocal Rank Fusion across semantic, graph, recency, and confidence signals."""
        # Build ranked lists for each signal
        sem_ranked = sorted(candidates, key=lambda rid: semantic.get(rid, 0.0), reverse=True)
        graph_ranked = sorted(candidates, key=lambda rid: graph.get(rid, 0.0), reverse=True)
        recency_ranked = sorted(
            candidates,
            key=lambda rid: self._records[rid].created_at,
            reverse=True,
        )
        confidence_ranked = sorted(
            candidates,
            key=lambda rid: self._records[rid].confidence,
            reverse=True,
        )

        signal_ranks = [
            (sem_ranked, self._weights["semantic"]),
            (graph_ranked, self._weights["graph"]),
            (recency_ranked, self._weights["recency"]),
            (confidence_ranked, self._weights["confidence"]),
        ]

        rrf_scores: dict[str, float] = defaultdict(float)
        for ranked_list, weight in signal_ranks:
            for rank, rid in enumerate(ranked_list):
                rrf_scores[rid] += weight * (1.0 / (k + rank + 1))

        sem_max = max(semantic.values(), default=1.0)
        graph_max = max(graph.values(), default=1.0)

        results: list[QueryResult] = []
        for rid in candidates:
            record = self._records[rid]
            sem_norm = semantic.get(rid, 0.0) / sem_max
            graph_norm = graph.get(rid, 0.0) / graph_max
            age_hours = max((ref_now - record.created_at).total_seconds() / 3600.0, 0.0)
            recency_score = 1.0 / (1.0 + age_hours / 24.0)

            rationale: list[str] = ["rrf"]
            if sem_norm > 0.0:
                rationale.append("semantic_match")
            if graph_norm > 0.0:
                rationale.append("graph_relation")

            results.append(
                QueryResult(
                    record=record,
                    score=rrf_scores[rid],
                    semantic_score=sem_norm,
                    graph_score=graph_norm,
                    recency_score=recency_score,
                    confidence_score=record.confidence,
                    rationale=rationale,
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    def _fuse_semantic(
        self,
        bm25: dict[str, float],
        embedding: dict[str, float],
        candidates: set[str],
    ) -> dict[str, float]:
        """Fuse BM25 and embedding scores based on scoring mode."""
        if self._scoring == "bm25":
            return {rid: bm25.get(rid, 0.0) for rid in candidates if bm25.get(rid, 0.0) > 0}
        if self._scoring == "embedding":
            return {rid: embedding.get(rid, 0.0) for rid in candidates if embedding.get(rid, 0.0) > 0}
        # hybrid: configurable embedding/BM25 fusion
        emb_weight = self._scoring_weights.semantic_embedding
        bm25_weight = self._scoring_weights.semantic_bm25
        fused: dict[str, float] = {}
        for rid in candidates:
            emb = embedding.get(rid, 0.0)
            bm = bm25.get(rid, 0.0)
            score = emb_weight * emb + bm25_weight * bm
            if score > 0.0:
                fused[rid] = score
        return fused
