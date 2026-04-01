from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class RetrievedChunk:
    record_id: str
    score: float
    source: str


class VectorStoreAdapter(Protocol):
    def upsert(self, record_id: str, text: str, metadata: dict[str, object]) -> None: ...

    def search(self, query: str, top_k: int) -> list[RetrievedChunk]: ...


class GraphStoreAdapter(Protocol):
    def attach_entities(self, record_id: str, entities: list[str]) -> None: ...

    def add_relation(self, left: str, relation: str, right: str, weight: float = 1.0) -> None: ...

    def neighbor_records(self, entities: list[str], hops: int) -> dict[str, float]: ...


class TrustPolicyAdapter(Protocol):
    def is_source_allowed(self, source: str) -> bool: ...

    def score(self, *, confidence: float, source: str, created_at: datetime) -> float: ...
