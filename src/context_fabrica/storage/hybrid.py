from __future__ import annotations

from dataclasses import dataclass

from ..config import HybridStoreSettings
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
    def __init__(self, settings: HybridStoreSettings) -> None:
        self.settings = settings
        self.postgres = PostgresPgvectorAdapter(settings.postgres)
        self.kuzu = KuzuGraphProjectionAdapter(settings.kuzu)

    def bootstrap_plan(self) -> dict[str, list[str]]:
        return {
            "postgres": self.postgres.bootstrap_statements(),
            "kuzu": self.kuzu.bootstrap_statements(),
        }

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
