from __future__ import annotations

import argparse
import importlib.util
import json

from .config import PostgresSettings
from .storage.postgres import PostgresPgvectorAdapter


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify context-fabrica runtime dependencies and Postgres health")
    parser.add_argument("--dsn", required=True)
    args = parser.parse_args()

    modules = {
        "psycopg": _has_module("psycopg"),
        "pgvector": _has_module("pgvector"),
        "kuzu": _has_module("kuzu"),
        "fastembed": _has_module("fastembed"),
    }

    adapter = PostgresPgvectorAdapter(PostgresSettings(dsn=args.dsn))
    health = adapter.health_probe()

    payload = {
        "ok": bool(health.get("ok", False) and health.get("vector_extension", False)),
        "modules": modules,
        "postgres": health,
    }
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
