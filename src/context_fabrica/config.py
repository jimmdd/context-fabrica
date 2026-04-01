from __future__ import annotations

from dataclasses import dataclass, field


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
