INSERT INTO context_fabrica.memory_records (
    record_id,
    text_content,
    source,
    domain,
    confidence,
    memory_stage,
    memory_kind,
    tags,
    metadata,
    created_at,
    valid_from,
    valid_to,
    supersedes,
    reviewed_at
) VALUES (
    'smoke-auth-1',
    'AuthService depends on TokenSigner and calls KeyStore.',
    'smoke-test',
    'platform',
    0.92,
    'canonical',
    'fact',
    '["auth", "platform"]'::jsonb,
    '{"repo": "context-fabrica", "kind": "smoke-test"}'::jsonb,
    now(),
    now(),
    NULL,
    NULL,
    now()
)
ON CONFLICT (record_id) DO UPDATE SET
    text_content = EXCLUDED.text_content,
    source = EXCLUDED.source,
    domain = EXCLUDED.domain,
    confidence = EXCLUDED.confidence,
    memory_stage = EXCLUDED.memory_stage,
    memory_kind = EXCLUDED.memory_kind,
    tags = EXCLUDED.tags,
    metadata = EXCLUDED.metadata,
    created_at = EXCLUDED.created_at,
    valid_from = EXCLUDED.valid_from,
    valid_to = EXCLUDED.valid_to,
    supersedes = EXCLUDED.supersedes,
    reviewed_at = EXCLUDED.reviewed_at;

DELETE FROM context_fabrica.memory_chunks WHERE record_id = 'smoke-auth-1';
INSERT INTO context_fabrica.memory_chunks (record_id, chunk_text, embedding, chunk_index)
VALUES (
    'smoke-auth-1',
    'AuthService depends on TokenSigner and calls KeyStore.',
    ('[' || array_to_string(array_fill(0.01::text, ARRAY[1536]), ',') || ']')::vector,
    0
);

DELETE FROM context_fabrica.memory_relations WHERE record_id = 'smoke-auth-1';
INSERT INTO context_fabrica.memory_relations (record_id, source_entity, relation_type, target_entity, weight)
VALUES
    ('smoke-auth-1', 'authservice', 'DEPENDS_ON', 'tokensigner', 1.0),
    ('smoke-auth-1', 'authservice', 'CALLS', 'keystore', 1.0);

SELECT record_id, domain, confidence
FROM context_fabrica.memory_records
WHERE record_id = 'smoke-auth-1';

SELECT record_id, chunk_index
FROM context_fabrica.memory_chunks
WHERE record_id = 'smoke-auth-1';

SELECT source_entity, relation_type, target_entity
FROM context_fabrica.memory_relations
WHERE record_id = 'smoke-auth-1'
ORDER BY relation_type, target_entity;
