from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import HybridStoreSettings
from ..embedding import Embedder, build_default_embedder, chunk_text
from ..models import KnowledgeRecord
from ..projection import GraphProjection, build_graph_projection
from .kuzu import KuzuGraphProjectionAdapter
from .postgres import PostgresPgvectorAdapter


@dataclass(frozen=True)
class HybridWritePlan:
    postgres_record_statement: str
    postgres_record_payload: tuple[object, ...]
    postgres_relation_rows: list[tuple[str, str, str, str, float]]
    kuzu_projection_statements: list[str]
    graph_projection: GraphProjection


class HybridMemoryStore:
    def __init__(self, settings: HybridStoreSettings, *, embedder: Embedder | None = None) -> None:
        self.settings = settings
        self.postgres = PostgresPgvectorAdapter(settings.postgres)
        self.kuzu = KuzuGraphProjectionAdapter(settings.kuzu)
        self.embedder = embedder or build_default_embedder(dimensions=settings.postgres.embedding_dimensions)

    def bootstrap_plan(self) -> dict[str, list[str]]:
        return {
            "postgres": self.postgres.bootstrap_statements(),
            "kuzu": self.kuzu.bootstrap_statements(),
        }

    def bootstrap_postgres(self) -> None:
        self.postgres.bootstrap()

    def write_plan(self, record: KnowledgeRecord) -> HybridWritePlan:
        projection = build_graph_projection(record)
        relation_rows = [
            (record.record_id, rel.source_entity, rel.relation, rel.target_entity, rel.weight)
            for rel in projection.relations
        ]
        return HybridWritePlan(
            postgres_record_statement=self.postgres.upsert_record_statement(),
            postgres_record_payload=self.postgres.upsert_record_payload(record),
            postgres_relation_rows=relation_rows,
            kuzu_projection_statements=self.kuzu.project_statements(
                projection,
                domain=record.domain,
                source=record.source,
            ),
            graph_projection=projection,
        )

    def write_record(
        self,
        record: KnowledgeRecord,
        *,
        chunks: list[tuple[str, list[float], int]] | None = None,
    ) -> HybridWritePlan:
        plan = self.write_plan(record)
        self.postgres.upsert_record(record)
        if chunks is not None:
            self.postgres.replace_chunks(record.record_id, chunks)
        if plan.postgres_relation_rows:
            self.postgres.replace_relations(record.record_id, plan.postgres_relation_rows)
        if record.stage in {"canonical", "pattern"}:
            self.postgres.enqueue_projection(record.record_id)
        return plan

    def write_text(
        self,
        record: KnowledgeRecord,
        *,
        max_chars: int = 800,
        overlap: int = 120,
    ) -> HybridWritePlan:
        chunks = [
            (chunk.text, self.embedder.embed(chunk.text), chunk.chunk_index)
            for chunk in chunk_text(record.text, max_chars=max_chars, overlap=overlap)
        ]
        if not chunks:
            chunks = [(record.text, self.embedder.embed(record.text), 0)]
        return self.write_record(record, chunks=chunks)

    def promote_record(
        self,
        source_record_id: str,
        *,
        reviewed_at: datetime | None = None,
        reason: str = "manual_review",
    ) -> KnowledgeRecord:
        record = self.postgres.fetch_record(source_record_id)
        if record is None:
            raise KeyError(source_record_id)
        record.stage = "canonical"
        record.reviewed_at = reviewed_at or datetime.now(tz=timezone.utc)
        if record.kind == "note":
            record.kind = "fact"
        self.postgres.upsert_record(record)
        self.postgres.record_promotion(source_record_id, record.record_id, reason, record.reviewed_at)
        self.postgres.enqueue_projection(record.record_id)
        return record

    def semantic_search(
        self,
        query_embedding: list[float],
        *,
        domain: str | None = None,
        top_k: int = 5,
    ) -> list:
        return self.postgres.semantic_search(query_embedding, domain=domain, top_k=top_k)
