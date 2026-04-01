from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import DomainMemoryEngine


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="context-fabrica CLI")
    parser.add_argument("--dataset", type=Path, required=True, help="Path to JSONL file with records")
    parser.add_argument("--query", required=True, help="Natural-language query")
    parser.add_argument("--top-k", type=int, default=5)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    engine = DomainMemoryEngine()
    for line in args.dataset.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        engine.ingest(
            payload["text"],
            source=payload.get("source", "unknown"),
            domain=payload.get("domain", "global"),
            confidence=float(payload.get("confidence", 0.6)),
            tags=payload.get("tags", []),
            metadata=payload.get("metadata", {}),
            record_id=payload.get("record_id"),
        )

    results = engine.query(args.query, top_k=args.top_k)
    for idx, item in enumerate(results, start=1):
        print(f"{idx}. {item.record.record_id} score={item.score:.3f} rationale={','.join(item.rationale)}")
        print(f"   {item.record.text[:200]}")


if __name__ == "__main__":
    main()
