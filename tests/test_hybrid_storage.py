from src.context_fabrica import HybridMemoryStore, HybridStoreSettings, KnowledgeRecord, KuzuSettings, PostgresSettings


def test_postgres_bootstrap_includes_pgvector_schema() -> None:
    store = HybridMemoryStore(
        HybridStoreSettings(
            postgres=PostgresSettings(dsn="postgresql://localhost/test"),
            kuzu=KuzuSettings(path="./tmp-kuzu"),
        )
    )

    bootstrap = store.bootstrap_plan()["postgres"]
    assert any("CREATE EXTENSION IF NOT EXISTS vector" in statement for statement in bootstrap)
    assert any("memory_records" in statement for statement in bootstrap)
    assert any("memory_chunks" in statement for statement in bootstrap)
    assert any("memory_stage" in statement for statement in bootstrap)


def test_kuzu_bootstrap_includes_record_and_entity_tables() -> None:
    store = HybridMemoryStore(
        HybridStoreSettings(
            postgres=PostgresSettings(dsn="postgresql://localhost/test"),
            kuzu=KuzuSettings(path="./tmp-kuzu"),
        )
    )

    bootstrap = store.bootstrap_plan()["kuzu"]
    assert any("CREATE NODE TABLE IF NOT EXISTS MemoryRecord" in statement for statement in bootstrap)
    assert any("CREATE NODE TABLE IF NOT EXISTS Entity" in statement for statement in bootstrap)
    assert any("CREATE REL TABLE IF NOT EXISTS RELATED" in statement for statement in bootstrap)


def test_write_plan_generates_postgres_payload_and_graph_projection() -> None:
    store = HybridMemoryStore(
        HybridStoreSettings(
            postgres=PostgresSettings(dsn="postgresql://localhost/test"),
            kuzu=KuzuSettings(path="./tmp-kuzu"),
        )
    )
    record = KnowledgeRecord(
        record_id="r1",
        text="AuthService depends on TokenSigner and calls KeyStore.",
        source="design-doc",
        domain="platform",
        confidence=0.85,
    )

    plan = store.write_plan(record)

    assert plan.postgres_record_payload[0] == "r1"
    assert plan.graph_projection.record_id == "r1"
    assert "authservice" in plan.graph_projection.entities
    assert any(row[2] == "DEPENDS_ON" for row in plan.postgres_relation_rows)
    assert any("MERGE (r:MemoryRecord" in statement for statement in plan.kuzu_projection_statements)
    assert plan.postgres_record_payload[5] == "canonical"


def test_postgres_search_statement_filters_by_domain_and_validity() -> None:
    store = HybridMemoryStore(
        HybridStoreSettings(
            postgres=PostgresSettings(dsn="postgresql://localhost/test"),
            kuzu=KuzuSettings(path="./tmp-kuzu"),
        )
    )

    statement = store.postgres.search_statement()
    assert "r.domain = %s" in statement
    assert "r.valid_from <= %s" in statement
    assert "r.valid_to IS NULL OR r.valid_to >= %s" in statement
    assert "r.memory_stage <> 'staged'" in statement


def test_write_record_calls_postgres_write_methods(mocker) -> None:
    store = HybridMemoryStore(
        HybridStoreSettings(
            postgres=PostgresSettings(dsn="postgresql://localhost/test"),
            kuzu=KuzuSettings(path="./tmp-kuzu"),
        )
    )
    upsert = mocker.patch.object(store.postgres, "upsert_record")
    replace_chunks = mocker.patch.object(store.postgres, "replace_chunks")
    replace_relations = mocker.patch.object(store.postgres, "replace_relations")
    enqueue_projection = mocker.patch.object(store.postgres, "enqueue_projection")

    record = KnowledgeRecord(
        record_id="r-live",
        text="AuthService depends on TokenSigner.",
        source="design-doc",
        domain="platform",
        confidence=0.8,
    )

    plan = store.write_record(record, chunks=[("AuthService depends on TokenSigner.", [0.1] * 1536, 0)])

    upsert.assert_called_once_with(record)
    replace_chunks.assert_called_once()
    replace_relations.assert_called_once_with(record.record_id, plan.postgres_relation_rows)
    enqueue_projection.assert_called_once_with(record.record_id)


def test_write_text_generates_chunks_with_default_embedder(mocker) -> None:
    store = HybridMemoryStore(
        HybridStoreSettings(
            postgres=PostgresSettings(dsn="postgresql://localhost/test"),
            kuzu=KuzuSettings(path="./tmp-kuzu"),
        )
    )
    write_record = mocker.patch.object(store, "write_record")
    record = KnowledgeRecord(record_id="r2", text="alpha " * 300, source="design-doc", confidence=0.8)

    store.write_text(record)

    assert write_record.called
    chunks = write_record.call_args.kwargs["chunks"]
    assert len(chunks) > 1


def test_promote_record_persists_promotion_provenance(mocker) -> None:
    store = HybridMemoryStore(
        HybridStoreSettings(
            postgres=PostgresSettings(dsn="postgresql://localhost/test"),
            kuzu=KuzuSettings(path="./tmp-kuzu"),
        )
    )
    record = KnowledgeRecord(record_id="draft-promote", text="Draft TODO", stage="staged", kind="note")
    fetch = mocker.patch.object(store.postgres, "fetch_record", return_value=record)
    upsert = mocker.patch.object(store.postgres, "upsert_record")
    record_promotion = mocker.patch.object(store.postgres, "record_promotion")
    enqueue = mocker.patch.object(store.postgres, "enqueue_projection")

    promoted = store.promote_record("draft-promote", reason="reviewed")

    fetch.assert_called_once_with("draft-promote")
    upsert.assert_called_once_with(promoted)
    record_promotion.assert_called_once()
    enqueue.assert_called_once_with("draft-promote")
