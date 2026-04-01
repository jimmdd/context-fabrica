CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS context_fabrica;

CREATE TABLE IF NOT EXISTS context_fabrica.memory_records (
    record_id TEXT PRIMARY KEY,
    text_content TEXT NOT NULL,
    source TEXT NOT NULL,
    domain TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    memory_stage TEXT NOT NULL DEFAULT 'canonical',
    memory_kind TEXT NOT NULL DEFAULT 'fact',
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NULL,
    supersedes TEXT NULL,
    reviewed_at TIMESTAMPTZ NULL
);

ALTER TABLE context_fabrica.memory_records ADD COLUMN IF NOT EXISTS memory_stage TEXT NOT NULL DEFAULT 'canonical';
ALTER TABLE context_fabrica.memory_records ADD COLUMN IF NOT EXISTS memory_kind TEXT NOT NULL DEFAULT 'fact';
ALTER TABLE context_fabrica.memory_records ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ NULL;

CREATE TABLE IF NOT EXISTS context_fabrica.memory_chunks (
    chunk_id BIGSERIAL PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES context_fabrica.memory_records(record_id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    embedding vector(1536) NULL,
    chunk_index INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS context_fabrica.memory_relations (
    relation_id BIGSERIAL PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES context_fabrica.memory_records(record_id) ON DELETE CASCADE,
    source_entity TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    target_entity TEXT NOT NULL,
    weight DOUBLE PRECISION NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS context_fabrica.memory_promotions (
    promotion_id BIGSERIAL PRIMARY KEY,
    source_record_id TEXT NOT NULL REFERENCES context_fabrica.memory_records(record_id) ON DELETE CASCADE,
    target_record_id TEXT NOT NULL REFERENCES context_fabrica.memory_records(record_id) ON DELETE CASCADE,
    promoted_at TIMESTAMPTZ NOT NULL,
    reason TEXT NOT NULL,
    UNIQUE (source_record_id, target_record_id)
);

CREATE TABLE IF NOT EXISTS context_fabrica.projection_jobs (
    job_id BIGSERIAL PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES context_fabrica.memory_records(record_id) ON DELETE CASCADE,
    job_type TEXT NOT NULL DEFAULT 'project_record',
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (record_id, job_type)
);

CREATE INDEX IF NOT EXISTS idx_context_fabrica_records_domain ON context_fabrica.memory_records(domain);
CREATE INDEX IF NOT EXISTS idx_context_fabrica_records_stage ON context_fabrica.memory_records(memory_stage);
CREATE INDEX IF NOT EXISTS idx_context_fabrica_records_validity ON context_fabrica.memory_records(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_context_fabrica_relations_source ON context_fabrica.memory_relations(source_entity);
CREATE INDEX IF NOT EXISTS idx_context_fabrica_relations_target ON context_fabrica.memory_relations(target_entity);
CREATE INDEX IF NOT EXISTS idx_context_fabrica_chunks_embedding ON context_fabrica.memory_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_context_fabrica_projection_jobs_status ON context_fabrica.projection_jobs(status, updated_at);
