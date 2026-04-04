from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from math import sqrt
from typing import Iterable, Literal
from uuid import uuid4

from .adapters import Reranker
from .config import NamespacePolicy, ScoringWeights
from .embedding import Embedder, HashEmbedder
from .entity import extract_entities, extract_relations
from .graph import KnowledgeGraph
from .index import LexicalSemanticIndex
from .models import KnowledgeRecord, MemoryKind, MemoryStage, QueryResult, Relation
from .policy import decide_memory_tier, promote_record
from .synthesis import build_observation_record
from .temporal import extract_time_range, temporal_overlap_score

ScoringMode = Literal["hybrid", "embedding", "bm25", "rrf"]


class DomainMemoryEngine:
    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
        scoring: ScoringMode = "hybrid",
        weights: ScoringWeights | None = None,
        reranker: Reranker | None = None,
        rerank_weight: float = 0.15,
        namespace_policies: dict[str, NamespacePolicy] | None = None,
    ) -> None:
        self._records: dict[str, KnowledgeRecord] = {}
        self._index = LexicalSemanticIndex()
        self._graph = KnowledgeGraph()
        self._embedder = embedder or HashEmbedder()
        self._embeddings: dict[str, list[float]] = {}
        self._scoring = scoring
        self._scoring_weights = weights or ScoringWeights()
        self._weights = self._weight_map(self._scoring_weights)
        self._reranker = reranker
        self._rerank_weight = max(0.0, min(rerank_weight, 1.0))
        self._namespace_policies = dict(namespace_policies or {})

    @property
    def records(self) -> dict[str, KnowledgeRecord]:
        return self._records

    def ingest(
        self,
        text: str,
        *,
        source: str = "unknown",
        domain: str = "global",
        namespace: str = "default",
        confidence: float = 0.6,
        tags: Iterable[str] | None = None,
        metadata: dict[str, object] | None = None,
        record_id: str | None = None,
        auto_stage: bool = True,
        entities: list[str] | None = None,
        relations: list[Relation] | None = None,
        stage: MemoryStage | None = None,
        kind: MemoryKind | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        infer_occurrence: bool = True,
    ) -> KnowledgeRecord:
        rid = record_id or str(uuid4())
        created_at = datetime.now(tz=timezone.utc)
        inferred_occurrence = None
        if infer_occurrence and occurred_from is None and occurred_to is None:
            inferred_occurrence = extract_time_range(text, now=created_at)
        record = KnowledgeRecord(
            record_id=rid,
            text=text,
            source=source,
            domain=domain,
            namespace=namespace,
            created_at=created_at,
            confidence=max(0.0, min(1.0, confidence)),
            tags=list(tags or []),
            metadata=dict(metadata or {}),
            occurred_from=occurred_from or (inferred_occurrence[0] if inferred_occurrence else None),
            occurred_to=occurred_to or (inferred_occurrence[1] if inferred_occurrence else None),
        )
        if auto_stage:
            decision = decide_memory_tier(record)
            record.stage = decision.stage
            record.kind = decision.kind
            record.metadata.setdefault("promotion_rationale", decision.rationale)
        if stage is not None:
            record.stage = stage
        if kind is not None:
            record.kind = kind
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
        hops: int | None = None,
        domain: str | None = None,
        namespace: str | None = None,
        now: datetime | None = None,
        as_of: datetime | None = None,
        include_staged: bool | None = None,
        time_range: tuple[datetime, datetime] | None = None,
        rerank_top_n: int | None = None,
    ) -> list[QueryResult]:
        ref_now = now or datetime.now(tz=timezone.utc)
        point_in_time = as_of or ref_now
        policy = self._namespace_policies.get(namespace) if namespace is not None else None
        scoring_weights = policy.weights if policy and policy.weights is not None else self._scoring_weights
        weights = self._weight_map(scoring_weights)
        effective_hops = hops if hops is not None else (policy.default_hops if policy and policy.default_hops is not None else 2)
        effective_include_staged = (
            include_staged
            if include_staged is not None
            else (policy.include_staged if policy and policy.include_staged is not None else False)
        )
        effective_rerank_top_n = (
            rerank_top_n
            if rerank_top_n is not None
            else (policy.rerank_top_n if policy is not None else 0)
        )
        candidate_limit = max(top_k, effective_rerank_top_n)

        bm25_scores = self._index.score(prompt)
        embedding_scores = self._embedding_scores(prompt) if self._scoring != "bm25" else {}
        query_entities = extract_entities(prompt)
        graph = self._graph.records_for_entities(query_entities, hops=effective_hops)
        resolved_time_range = time_range or extract_time_range(prompt, now=ref_now)

        all_ids = set(bm25_scores) | set(embedding_scores) | set(graph)
        temporal = self._temporal_scores(
            resolved_time_range,
            point_in_time=point_in_time,
            domain=domain,
            namespace=namespace,
            include_staged=effective_include_staged,
            policy=policy,
        )
        if resolved_time_range is not None:
            all_ids |= set(temporal)
        all_ids = self._filter_candidates(
            all_ids,
            point_in_time=point_in_time,
            domain=domain,
            namespace=namespace,
            include_staged=effective_include_staged,
            policy=policy,
        )

        semantic = self._fuse_semantic(
            bm25_scores,
            embedding_scores,
            all_ids,
            scoring_weights=scoring_weights,
        )

        if self._scoring == "rrf":
            rrf_results = self._score_rrf(
                all_ids,
                semantic,
                graph,
                temporal,
                ref_now,
                candidate_limit,
                weights=weights,
            )
            reranked_rrf = self._apply_reranker(prompt, rrf_results, effective_rerank_top_n)
            return reranked_rrf[:top_k]

        sem_max = max(semantic.values(), default=1.0)
        graph_max = max(graph.values(), default=1.0)
        temporal_max = max(temporal.values(), default=1.0)

        ranked: list[QueryResult] = []
        for rid in all_ids:
            record = self._records[rid]
            sem_norm = semantic.get(rid, 0.0) / sem_max
            graph_norm = graph.get(rid, 0.0) / graph_max
            temporal_norm = temporal.get(rid, 0.0) / temporal_max

            age_hours = max((ref_now - record.created_at).total_seconds() / 3600.0, 0.0)
            recency_score = 1.0 / (1.0 + age_hours / 24.0)
            confidence_score = record.confidence

            final_score = (
                weights["semantic"] * sem_norm
                + weights["graph"] * graph_norm
                + weights["temporal"] * temporal_norm
                + weights["recency"] * recency_score
                + weights["confidence"] * confidence_score
            )

            rationale: list[str] = []
            if sem_norm > 0.0:
                rationale.append("semantic_match")
            if graph_norm > 0.0:
                rationale.append("graph_relation")
            if temporal_norm > 0.0:
                rationale.append("temporal_match")
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
                    temporal_score=temporal_norm,
                    recency_score=recency_score,
                    confidence_score=confidence_score,
                    rationale=rationale,
                )
            )

        ranked.sort(key=lambda item: item.score, reverse=True)
        reranked = self._apply_reranker(prompt, ranked[:candidate_limit], effective_rerank_top_n)
        return reranked[:top_k]

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
            namespace=old.namespace,
            confidence=confidence if confidence is not None else old.confidence,
            tags=list(old.tags),
            metadata={**old.metadata, "supersession_reason": reason},
            record_id=record_id,
            entities=entities,
            relations=relations,
            occurred_from=old.occurred_from,
            occurred_to=old.occurred_to,
        )
        new.supersedes = old_record_id
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

    def synthesize_observation(
        self,
        record_ids: list[str],
        *,
        record_id: str | None = None,
        source: str = "observation-synthesizer",
        max_sentences: int = 3,
    ) -> KnowledgeRecord:
        records = [self._records[rid] for rid in record_ids if rid in self._records]
        observation = build_observation_record(
            records,
            record_id=record_id,
            source=source,
            max_sentences=max_sentences,
        )
        return self.ingest(
            observation.text,
            source=observation.source,
            domain=observation.domain,
            namespace=observation.namespace,
            confidence=observation.confidence,
            tags=observation.tags,
            metadata=observation.metadata,
            record_id=observation.record_id,
            auto_stage=False,
            stage=observation.stage,
            kind=observation.kind,
            occurred_from=observation.occurred_from,
            occurred_to=observation.occurred_to,
        )

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

    @staticmethod
    def _weight_map(weights: ScoringWeights) -> dict[str, float]:
        raw = {
            "semantic": weights.semantic,
            "graph": weights.graph,
            "temporal": weights.temporal,
            "recency": weights.recency,
            "confidence": weights.confidence,
        }
        total = sum(raw.values()) or 1.0
        return {k: v / total for k, v in raw.items()}

    def _filter_candidates(
        self,
        candidates: set[str],
        *,
        point_in_time: datetime,
        domain: str | None,
        namespace: str | None,
        include_staged: bool,
        policy: NamespacePolicy | None,
    ) -> set[str]:
        result = candidates
        if domain:
            result = {rid for rid in result if self._records[rid].domain == domain}
        if namespace:
            result = {rid for rid in result if self._records[rid].namespace == namespace}
        result = {rid for rid in result if self._is_valid(self._records[rid], point_in_time)}
        if not include_staged:
            result = {rid for rid in result if self._records[rid].stage != "staged"}
        if policy is not None and policy.min_confidence is not None:
            result = {rid for rid in result if self._records[rid].confidence >= policy.min_confidence}
        if policy is not None and policy.source_allowlist:
            allowed_sources = set(policy.source_allowlist)
            result = {rid for rid in result if self._records[rid].source in allowed_sources}
        return result

    def _temporal_scores(
        self,
        query_range: tuple[datetime, datetime] | None,
        *,
        point_in_time: datetime,
        domain: str | None,
        namespace: str | None,
        include_staged: bool,
        policy: NamespacePolicy | None,
    ) -> dict[str, float]:
        if query_range is None:
            return {}
        eligible = self._filter_candidates(
            set(self._records),
            point_in_time=point_in_time,
            domain=domain,
            namespace=namespace,
            include_staged=include_staged,
            policy=policy,
        )
        scores: dict[str, float] = {}
        for rid in eligible:
            record = self._records[rid]
            score = temporal_overlap_score(record.occurred_from, record.occurred_to, query_range)
            if score > 0.0:
                scores[rid] = score
        return scores

    def _score_rrf(
        self,
        candidates: set[str],
        semantic: dict[str, float],
        graph: dict[str, float],
        temporal: dict[str, float],
        ref_now: datetime,
        top_k: int,
        *,
        weights: dict[str, float],
        k: int = 60,
    ) -> list[QueryResult]:
        """Reciprocal Rank Fusion across semantic, graph, temporal, recency, and confidence signals."""
        sem_ranked = sorted(candidates, key=lambda rid: semantic.get(rid, 0.0), reverse=True)
        graph_ranked = sorted(candidates, key=lambda rid: graph.get(rid, 0.0), reverse=True)
        temporal_ranked = sorted(candidates, key=lambda rid: temporal.get(rid, 0.0), reverse=True)
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
            (sem_ranked, weights["semantic"]),
            (graph_ranked, weights["graph"]),
            (temporal_ranked, weights["temporal"]),
            (recency_ranked, weights["recency"]),
            (confidence_ranked, weights["confidence"]),
        ]

        rrf_scores: dict[str, float] = defaultdict(float)
        for ranked_list, weight in signal_ranks:
            for rank, rid in enumerate(ranked_list):
                rrf_scores[rid] += weight * (1.0 / (k + rank + 1))

        sem_max = max(semantic.values(), default=1.0)
        graph_max = max(graph.values(), default=1.0)
        temporal_max = max(temporal.values(), default=1.0)

        results: list[QueryResult] = []
        for rid in candidates:
            record = self._records[rid]
            sem_norm = semantic.get(rid, 0.0) / sem_max
            graph_norm = graph.get(rid, 0.0) / graph_max
            temporal_norm = temporal.get(rid, 0.0) / temporal_max
            age_hours = max((ref_now - record.created_at).total_seconds() / 3600.0, 0.0)
            recency_score = 1.0 / (1.0 + age_hours / 24.0)

            rationale: list[str] = ["rrf"]
            if sem_norm > 0.0:
                rationale.append("semantic_match")
            if graph_norm > 0.0:
                rationale.append("graph_relation")
            if temporal_norm > 0.0:
                rationale.append("temporal_match")

            results.append(
                QueryResult(
                    record=record,
                    score=rrf_scores[rid],
                    semantic_score=sem_norm,
                    graph_score=graph_norm,
                    temporal_score=temporal_norm,
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
        *,
        scoring_weights: ScoringWeights,
    ) -> dict[str, float]:
        """Fuse BM25 and embedding scores based on scoring mode."""
        if self._scoring == "bm25":
            return {rid: bm25.get(rid, 0.0) for rid in candidates if bm25.get(rid, 0.0) > 0}
        if self._scoring == "embedding":
            return {rid: embedding.get(rid, 0.0) for rid in candidates if embedding.get(rid, 0.0) > 0}
        emb_weight = scoring_weights.semantic_embedding
        bm25_weight = scoring_weights.semantic_bm25
        fused: dict[str, float] = {}
        for rid in candidates:
            emb = embedding.get(rid, 0.0)
            bm = bm25.get(rid, 0.0)
            score = emb_weight * emb + bm25_weight * bm
            if score > 0.0:
                fused[rid] = score
        return fused

    def _apply_reranker(
        self,
        query: str,
        results: list[QueryResult],
        rerank_top_n: int,
    ) -> list[QueryResult]:
        if self._reranker is None or rerank_top_n <= 1 or len(results) <= 1:
            return results
        top_n = min(rerank_top_n, len(results))
        reranked: list[QueryResult] = []
        for result in results[:top_n]:
            rerank_score = max(min(self._reranker.score(query, result.record), 1.0), 0.0)
            adjusted = replace(
                result,
                score=((1.0 - self._rerank_weight) * result.score) + (self._rerank_weight * rerank_score),
                rerank_score=rerank_score,
                rationale=result.rationale + ["reranked"],
            )
            reranked.append(adjusted)
        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked + results[top_n:]
