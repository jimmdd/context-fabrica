from __future__ import annotations

from collections import defaultdict, deque

from .models import Relation


class KnowledgeGraph:
    def __init__(self) -> None:
        self._out_edges: dict[str, list[Relation]] = defaultdict(list)
        self._in_edges: dict[str, list[Relation]] = defaultdict(list)
        self._record_entities: dict[str, set[str]] = defaultdict(set)
        self._entity_records: dict[str, set[str]] = defaultdict(set)

    def add_relation(self, relation: Relation) -> None:
        self._out_edges[relation.source_entity].append(relation)
        self._in_edges[relation.target_entity].append(relation)

    def attach_record_entities(self, record_id: str, entities: list[str]) -> None:
        for entity in entities:
            self._record_entities[record_id].add(entity)
            self._entity_records[entity].add(record_id)

    def record_entities(self, record_id: str) -> set[str]:
        return set(self._record_entities.get(record_id, set()))

    def records_for_entities(self, entities: list[str], hops: int = 2) -> dict[str, float]:
        scores: dict[str, float] = defaultdict(float)
        seen: set[tuple[str, int]] = set()
        queue: deque[tuple[str, int, float]] = deque()

        for entity in entities:
            queue.append((entity, 0, 1.0))

        while queue:
            node, depth, weight = queue.popleft()
            state = (node, depth)
            if state in seen:
                continue
            seen.add(state)

            for record_id in self._entity_records.get(node, set()):
                scores[record_id] += weight

            if depth >= hops:
                continue

            for edge in self._out_edges.get(node, []):
                queue.append((edge.target_entity, depth + 1, weight * 0.65 * edge.weight))
            for edge in self._in_edges.get(node, []):
                queue.append((edge.source_entity, depth + 1, weight * 0.5 * edge.weight))

        return scores
