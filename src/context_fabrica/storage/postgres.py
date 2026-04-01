from __future__ import annotations

from contextlib import suppress
from importlib import import_module

from ..config import PostgresSettings
from ..models import KnowledgeRecord


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
            ") VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11, $12, $13, $14) "
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

    def search_statement(self) -> str:
        schema = self.settings.schema
        return (
            f"SELECT r.record_id, r.text_content, r.source, r.domain, r.confidence, r.memory_stage, r.memory_kind, c.chunk_text, "
            "1 - (c.embedding <=> $1) AS semantic_score "
            f"FROM {schema}.memory_chunks c "
            f"JOIN {schema}.memory_records r ON r.record_id = c.record_id "
            "WHERE ($2::text IS NULL OR r.domain = $2) "
            "AND r.valid_from <= $3 "
            "AND (r.valid_to IS NULL OR r.valid_to >= $3) "
            "AND r.memory_stage <> 'staged' "
            "ORDER BY c.embedding <=> $1 LIMIT $4;"
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
            record.tags,
            record.metadata,
            record.created_at,
            record.valid_from,
            record.valid_to,
            record.supersedes,
            record.reviewed_at,
        )

    def connect(self) -> object:
        with suppress(ModuleNotFoundError):
            psycopg = import_module("psycopg")
            return psycopg.connect(self.settings.dsn)
        raise ModuleNotFoundError("Install context-fabrica[postgres] to use the Postgres adapter")
