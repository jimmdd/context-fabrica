from __future__ import annotations

import argparse
import os
from pathlib import Path

from .config import HybridStoreSettings, KuzuSettings, PostgresSettings
from .storage.kuzu import KuzuGraphProjectionAdapter
from .storage.postgres import PostgresPgvectorAdapter
from .storage.projector import GraphProjectionWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="Run context-fabrica graph projection worker")
    parser.add_argument("--dsn", default=os.environ.get("CONTEXT_FABRICA_TEST_DSN", "postgresql:///context_fabrica"))
    parser.add_argument("--kuzu-path", default="./var/context-fabrica-graph")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--requeue-record")
    parser.add_argument("--requeue-all-canonical", action="store_true")
    parser.add_argument("--requeue-domain")
    args = parser.parse_args()

    Path(args.kuzu_path).parent.mkdir(parents=True, exist_ok=True)
    settings = HybridStoreSettings(
        postgres=PostgresSettings(dsn=args.dsn),
        kuzu=KuzuSettings(path=args.kuzu_path),
    )
    worker = GraphProjectionWorker(
        PostgresPgvectorAdapter(settings.postgres),
        KuzuGraphProjectionAdapter(settings.kuzu),
    )
    if args.status:
        for row in worker.postgres.list_projection_jobs(limit=args.batch_size):
            print(row)
        return
    if args.retry_failed:
        print(worker.postgres.retry_failed_jobs())
        return
    if args.requeue_record:
        print(worker.postgres.requeue_record_projection(args.requeue_record))
        return
    if args.requeue_all_canonical or args.requeue_domain:
        print(worker.postgres.requeue_canonical_projection(domain=args.requeue_domain))
        return
    if args.once:
        print(worker.process_pending(limit=args.batch_size))
        return
    worker.run_forever(batch_size=args.batch_size)


if __name__ == "__main__":
    main()
