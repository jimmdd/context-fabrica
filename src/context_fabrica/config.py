from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScoringWeights:
    """Weights for the hybrid ranking formula.

    The four signal weights (semantic, graph, recency, confidence) are
    normalized at query time so they don't need to sum to 1.0.

    The semantic_embedding and semantic_bm25 weights control the fusion
    within the semantic signal when using hybrid scoring mode.
    """
    semantic: float = 0.50
    graph: float = 0.30
    recency: float = 0.12
    confidence: float = 0.08
    # Sub-weights for semantic fusion in hybrid mode
    semantic_embedding: float = 0.70
    semantic_bm25: float = 0.30


@dataclass(frozen=True)
class PostgresSettings:
    dsn: str
    schema: str = "context_fabrica"
    embedding_dimensions: int = 1536
    application_name: str = "context-fabrica"


@dataclass(frozen=True)
class KuzuSettings:
    path: str
    database_name: str = "context-fabrica-graph"
    max_hops: int = 3


@dataclass(frozen=True)
class HybridStoreSettings:
    postgres: PostgresSettings
    kuzu: KuzuSettings
    relation_types: tuple[str, ...] = field(
        default_factory=lambda: (
            "DEPENDS_ON",
            "OWNS",
            "CALLS",
            "IMPLEMENTS",
            "DOCUMENTED_BY",
            "SUPERSEDES",
        )
    )
