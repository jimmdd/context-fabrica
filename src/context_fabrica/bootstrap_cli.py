from __future__ import annotations

import argparse
from pathlib import Path

from .config import HybridStoreSettings, KuzuSettings, PostgresSettings
from .project_memory_cli import bootstrap as bootstrap_project_memory
from .storage.hybrid import HybridMemoryStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap context-fabrica project memory and verify Postgres")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--kuzu-path", default="./var/context-fabrica-graph")
    args = parser.parse_args()

    payload = bootstrap_project_memory(args.root)
    store = HybridMemoryStore(
        HybridStoreSettings(
            postgres=PostgresSettings(dsn=args.dsn),
            kuzu=KuzuSettings(path=args.kuzu_path),
        )
    )
    store.bootstrap_postgres()

    print("context-fabrica bootstrap complete")
    print(f"- project memory: {payload['memory_root']}")
    print(f"- postgres dsn: {args.dsn}")
    print("Next steps:")
    print("1. PYTHONPATH=src python -m context_fabrica.demo_cli --dsn \"%s\" --project" % args.dsn)
    print("2. PYTHONPATH=src python -m context_fabrica.projector_cli --dsn \"%s\" --once" % args.dsn)


if __name__ == "__main__":
    main()
