from __future__ import annotations

from context_fabrica import DomainMemoryEngine, NamespacePolicy, TokenOverlapReranker


def main() -> None:
    engine = DomainMemoryEngine(
        reranker=TokenOverlapReranker(),
        namespace_policies={
            "fintech": NamespacePolicy(
                min_confidence=0.7,
                source_allowlist=("design-doc", "runbook"),
                rerank_top_n=5,
            ),
        },
    )

    # Ingest records with automatic entity/relation extraction
    engine.ingest(
        "PaymentsService depends on LedgerAdapter and calls RiskGateway.",
        source="design-doc",
        domain="fintech",
        namespace="fintech",
        confidence=0.9,
        record_id="r1",
    )
    engine.ingest(
        "LedgerAdapter writes transactions to event store.",
        source="runbook",
        domain="fintech",
        namespace="fintech",
        confidence=0.85,
        record_id="r2",
    )

    # Basic query with namespace policy enforcement
    print("=== Graph + semantic query ===")
    for hit in engine.query("How does PaymentsService interact with LedgerAdapter?", namespace="fintech", top_k=3):
        print(f"  {hit.record.record_id}  score={hit.score:.3f}  {hit.rationale}")

    # Temporal recall
    engine.ingest(
        "Quarterly incident review happened in June 2025.",
        source="runbook",
        domain="fintech",
        namespace="fintech",
        confidence=0.9,
        record_id="incident-june",
    )
    print("\n=== Temporal query ===")
    for hit in engine.query("What happened in June 2025?", namespace="fintech", top_k=3):
        print(f"  {hit.record.record_id}  score={hit.score:.3f}  temporal={hit.temporal_score:.2f}  {hit.rationale}")

    # Observation synthesis
    observation = engine.synthesize_observation(["r1", "r2"], record_id="obs-1")
    print(f"\n=== Synthesized observation ===")
    print(f"  {observation.record_id}  kind={observation.kind}  derived_from={observation.metadata['derived_from']}")
    print(f"  {observation.text[:120]}")


if __name__ == "__main__":
    main()
