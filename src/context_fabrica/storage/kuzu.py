from __future__ import annotations

from contextlib import suppress
from importlib import import_module

from ..config import KuzuSettings
from ..models import Relation
from ..projection import GraphProjection


class KuzuGraphProjectionAdapter:
    def __init__(self, settings: KuzuSettings) -> None:
        self.settings = settings

    def bootstrap_statements(self) -> list[str]:
        return [
            "CREATE NODE TABLE IF NOT EXISTS MemoryRecord(record_id STRING PRIMARY KEY, domain STRING, source STRING);",
            "CREATE NODE TABLE IF NOT EXISTS Entity(name STRING PRIMARY KEY);",
            "CREATE REL TABLE IF NOT EXISTS HAS_ENTITY(FROM MemoryRecord TO Entity, weight DOUBLE);",
            "CREATE REL TABLE IF NOT EXISTS RELATED(FROM Entity TO Entity, relation_type STRING, weight DOUBLE);",
        ]

    def project_statements(self, projection: GraphProjection, domain: str, source: str) -> list[str]:
        statements = [
            "MERGE (r:MemoryRecord {record_id: $record_id}) SET r.domain = $domain, r.source = $source"
        ]
        for entity in projection.entities:
            statements.append(
                "MERGE (e:Entity {name: $entity_name})"
            )
            statements.append(
                "MATCH (r:MemoryRecord {record_id: $record_id}), (e:Entity {name: $entity_name}) "
                "MERGE (r)-[:HAS_ENTITY {weight: 1.0}]->(e)"
            )
        for relation in projection.relations:
            statements.append(self._relation_statement(relation))
        return statements

    def neighbor_query(self) -> str:
        max_hops = self.settings.max_hops
        return (
            "MATCH (seed:Entity) WHERE seed.name IN $entities "
            f"MATCH p=(seed)-[:RELATED*1..{max_hops}]-(neighbor:Entity) "
            "RETURN neighbor.name AS entity_name, count(*) AS path_count ORDER BY path_count DESC LIMIT $limit"
        )

    def connect(self) -> object:
        with suppress(ModuleNotFoundError):
            kuzu = import_module("kuzu")
            database = kuzu.Database(self.settings.path)
            return kuzu.Connection(database)
        raise ModuleNotFoundError("Install context-fabrica[kuzu] to use the Kuzu adapter")

    def _relation_statement(self, relation: Relation) -> str:
        return (
            "MERGE (left:Entity {name: $source_entity}) "
            "MERGE (right:Entity {name: $target_entity}) "
            "MERGE (left)-[:RELATED {relation_type: $relation_type, weight: $weight}]->(right)"
        )
