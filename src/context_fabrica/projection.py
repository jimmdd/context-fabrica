from __future__ import annotations

from dataclasses import dataclass

from .entity import extract_entities, extract_relations
from .models import KnowledgeRecord, Relation


@dataclass(frozen=True)
class GraphProjection:
    record_id: str
    entities: list[str]
    relations: list[Relation]


def build_graph_projection(record: KnowledgeRecord) -> GraphProjection:
    entities = extract_entities(record.text)
    relations = [
        Relation(source_entity=left, relation=rel.upper(), target_entity=right, weight=1.0)
        for left, rel, right in extract_relations(record.text, entities)
    ]
    return GraphProjection(record_id=record.record_id, entities=entities, relations=relations)
