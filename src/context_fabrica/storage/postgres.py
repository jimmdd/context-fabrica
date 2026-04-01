from __future__ import annotations

from contextlib import suppress
import json
from importlib import import_module
from typing import Any, cast

from ..config import PostgresSettings
from ..models import KnowledgeRecord, QueryResult


class PostgresPgvectorAdapter:
    def __init__(self, settings: PostgresSettings) -> None:
        self.settings = settings

    def bootstrap_statements(self) -> list[str]:
        schema = self.settings.schema
        dims = self.settings.embedding_dimensions
        return [
            "CREATE EXTENSION IF NOT EXISTS vector;",
            f"CREATE SCHEMA IF NOT EXISTS {schema};",
            f"CREATE TABLE IF NOT EXISTS {schema}.memory_records ("
            "record_id TEXT PRIMARY KEY, "
            "text_content TEXT NOT NULL, "
            "source TEXT NOT NULL, "
            "domain TEXT NOT NULL, "
            "confidence DOUBLE PRECISION NOT NULL, "
            "memory_stage TEXT NOT NULL DEFAULT 'canonical', "
            "memory_kind TEXT NOT NULL DEFAULT 'fact', "
            "tags JSONB NOT NULL DEFAULT '[]'::jsonb, "
            "metadata JSONB NOT NULL DEFAULT '{}'::jsonb, "
            "created_at TIMESTAMPTZ NOT NULL, "
            "valid_from TIMESTAMPTZ NOT NULL, "
            "valid_to TIMESTAMPTZ NULL, "
            "supersedes TEXT NULL, "
            "reviewed_at TIMESTAMPTZ NULL"
            ");",
            f"ALTER TABLE {schema}.memory_records ADD COLUMN IF NOT EXISTS memory_stage TEXT NOT NULL DEFAULT 'canonical';",
            f"ALTER TABLE {schema}.memory_records ADD COLUMN IF NOT EXISTS memory_kind TEXT NOT NULL DEFAULT 'fact';",
            f"ALTER TABLE {schema}.memory_records ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ NULL;",
            f"CREATE TABLE IF NOT EXISTS {schema}.memory_chunks ("
            "chunk_id BIGSERIAL PRIMARY KEY, "
            f"record_id TEXT NOT NULL REFERENCES {schema}.memory_records(record_id) ON DELETE CASCADE, "
            "chunk_text TEXT NOT NULL, "
            f"embedding vector({dims}) NULL, "
            "chunk_index INTEGER NOT NULL DEFAULT 0"
            ");",
            f"CREATE TABLE IF NOT EXISTS {schema}.memory_relations ("
            "relation_id BIGSERIAL PRIMARY KEY, "
            f"record_id TEXT NOT NULL REFERENCES {schema}.memory_records(record_id) ON DELETE CASCADE, "
            "source_entity TEXT NOT NULL, "
            "relation_type TEXT NOT NULL, "
            "target_entity TEXT NOT NULL, "
            "weight DOUBLE PRECISION NOT NULL DEFAULT 1.0"
            ");",
            f"CREATE INDEX IF NOT EXISTS idx_{schema}_records_domain ON {schema}.memory_records(domain);",
            f"CREATE INDEX IF NOT EXISTS idx_{schema}_records_stage ON {schema}.memory_records(memory_stage);",
            f"CREATE INDEX IF NOT EXISTS idx_{schema}_records_validity ON {schema}.memory_records(valid_from, valid_to);",
            f"CREATE INDEX IF NOT EXISTS idx_{schema}_relations_source ON {schema}.memory_relations(source_entity);",
            f"CREATE INDEX IF NOT EXISTS idx_{schema}_relations_target ON {schema}.memory_relations(target_entity);",
            f"CREATE INDEX IF NOT EXISTS idx_{schema}_chunks_embedding ON {schema}.memory_chunks USING hnsw (embedding vector_cosine_ops);",
        ]

    def upsert_record_statement(self) -> str:
        schema = self.settings.schema
        return (
            f"INSERT INTO {schema}.memory_records ("
            "record_id, text_content, source, domain, confidence, memory_stage, memory_kind, tags, metadata, created_at, valid_from, valid_to, supersedes, reviewed_at"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s) "
            "ON CONFLICT (record_id) DO UPDATE SET "
            "text_content = EXCLUDED.text_content, "
            "source = EXCLUDED.source, "
            "domain = EXCLUDED.domain, "
            "confidence = EXCLUDED.confidence, "
            "memory_stage = EXCLUDED.memory_stage, "
            "memory_kind = EXCLUDED.memory_kind, "
            "tags = EXCLUDED.tags, "
            "metadata = EXCLUDED.metadata, "
            "created_at = EXCLUDED.created_at, "
            "valid_from = EXCLUDED.valid_from, "
            "valid_to = EXCLUDED.valid_to, "
            "supersedes = EXCLUDED.supersedes, "
            "reviewed_at = EXCLUDED.reviewed_at;"
        )

    def replace_chunks_statement(self) -> str:
        schema = self.settings.schema
        return (
            f"INSERT INTO {schema}.memory_chunks (record_id, chunk_text, embedding, chunk_index) "
            "VALUES (%s, %s, %s, %s);"
        )

    def delete_chunks_statement(self) -> str:
        schema = self.settings.schema
        return f"DELETE FROM {schema}.memory_chunks WHERE record_id = %s;"

    def replace_relations_statement(self) -> str:
        schema = self.settings.schema
        return (
            f"INSERT INTO {schema}.memory_relations (record_id, source_entity, relation_type, target_entity, weight) "
            "VALUES (%s, %s, %s, %s, %s);"
        )

    def delete_relations_statement(self) -> str:
        schema = self.settings.schema
        return f"DELETE FROM {schema}.memory_relations WHERE record_id = %s;"

    def fetch_record_statement(self) -> str:
        schema = self.settings.schema
        return (
            f"SELECT record_id, text_content, source, domain, confidence, memory_stage, memory_kind, tags, metadata, "
            "created_at, valid_from, valid_to, supersedes, reviewed_at "
            f"FROM {schema}.memory_records WHERE record_id = %s;"
        )

    def search_statement(self) -> str:
        schema = self.settings.schema
        return (
            f"SELECT r.record_id, r.text_content, r.source, r.domain, r.confidence, r.memory_stage, r.memory_kind, c.chunk_text, "
            "1 - (c.embedding <=> %s) AS semantic_score "
            f"FROM {schema}.memory_chunks c "
            f"JOIN {schema}.memory_records r ON r.record_id = c.record_id "
            "WHERE (%s::text IS NULL OR r.domain = %s) "
            "AND r.valid_from <= %s "
            "AND (r.valid_to IS NULL OR r.valid_to >= %s) "
            "AND r.memory_stage <> 'staged' "
            "ORDER BY c.embedding <=> %s LIMIT %s;"
        )

    def upsert_record_payload(self, record: KnowledgeRecord) -> tuple[object, ...]:
        return (
            record.record_id,
            record.text,
            record.source,
            record.domain,
            record.confidence,
            record.stage,
            record.kind,
            json.dumps(record.tags),
            json.dumps(record.metadata),
            record.created_at,
            record.valid_from,
            record.valid_to,
            record.supersedes,
            record.reviewed_at,
        )

    def bootstrap(self) -> None:
        conn = self.connect()
        with conn:
            with conn.cursor() as cur:
                for statement in self.bootstrap_statements():
                    cur.execute(statement)
            conn.commit()

    def upsert_record(self, record: KnowledgeRecord) -> None:
        conn = self.connect()
        with conn:
            self._ensure_vector_registered(conn)
            with conn.cursor() as cur:
                cur.execute(self.upsert_record_statement(), self.upsert_record_payload(record))
            conn.commit()

    def replace_chunks(self, record_id: str, chunks: list[tuple[str, list[float], int]]) -> None:
        conn = self.connect()
        with conn:
            self._ensure_vector_registered(conn)
            with conn.cursor() as cur:
                cur.execute(self.delete_chunks_statement(), (record_id,))
                for chunk_text, embedding, chunk_index in chunks:
                    cur.execute(
                        self.replace_chunks_statement(),
                        (record_id, chunk_text, embedding, chunk_index),
                    )
            conn.commit()

    def replace_relations(self, record_id: str, relations: list[tuple[str, str, str, str, float]]) -> None:
        conn = self.connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute(self.delete_relations_statement(), (record_id,))
                for row in relations:
                    cur.execute(self.replace_relations_statement(), row)
            conn.commit()

    def fetch_record(self, record_id: str) -> KnowledgeRecord | None:
        conn = self.connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute(self.fetch_record_statement(), (record_id,))
                row = cur.fetchone()
        if row is None:
            return None
        typed_row = cast(tuple[Any, ...], row)
        return KnowledgeRecord(
            record_id=str(typed_row[0]),
            text=str(typed_row[1]),
            source=str(typed_row[2]),
            domain=str(typed_row[3]),
            confidence=float(typed_row[4]),
            stage=cast(Any, str(typed_row[5])),
            kind=cast(Any, str(typed_row[6])),
            tags=list(cast(list[str], typed_row[7])),
            metadata=dict(cast(dict[str, Any], typed_row[8])),
            created_at=typed_row[9],
            valid_from=typed_row[10],
            valid_to=typed_row[11],
            supersedes=typed_row[12],
            reviewed_at=typed_row[13],
        )

    def semantic_search(
        self,
        query_embedding: list[float],
        *,
        domain: str | None = None,
        top_k: int = 5,
    ) -> list[QueryResult]:
        conn = self.connect()
        with conn:
            self._ensure_vector_registered(conn)
            with conn.cursor() as cur:
                now = self._now_utc()
                vector_query = self._vector_value(query_embedding)
                cur.execute(self.search_statement(), (vector_query, domain, domain, now, now, vector_query, top_k))
                rows = cur.fetchall()
        return [self._row_to_query_result(row) for row in rows]

    def connect(self) -> Any:
        with suppress(ModuleNotFoundError):
            psycopg = import_module("psycopg")
            return psycopg.connect(self.settings.dsn)
        raise ModuleNotFoundError("Install context-fabrica[postgres] to use the Postgres adapter")

    def _ensure_vector_registered(self, conn: Any) -> None:
        register_vector = import_module("pgvector.psycopg").register_vector
        register_vector(conn)

    def _vector_value(self, values: list[float]) -> Any:
        vector_cls = import_module("pgvector").Vector
        return vector_cls(values)

    def _row_to_query_result(self, row: tuple[Any, ...]) -> QueryResult:
        record = KnowledgeRecord(
            record_id=str(row[0]),
            text=str(row[1]),
            source=str(row[2]),
            domain=str(row[3]),
            confidence=float(row[4]),
            stage=cast(Any, str(row[5])),
            kind=cast(Any, str(row[6])),
        )
        return QueryResult(
            record=record,
            score=float(row[8]),
            semantic_score=float(row[8]),
            graph_score=0.0,
            recency_score=0.0,
            confidence_score=float(row[4]),
            rationale=["semantic_match", f"stage:{row[5]}", f"kind:{row[6]}"],
        )

    def _now_utc(self):
        from datetime import datetime, timezone

        return datetime.now(tz=timezone.utc)
