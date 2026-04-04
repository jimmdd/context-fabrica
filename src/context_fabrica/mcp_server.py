"""Zero-dependency MCP server for context-fabrica.

Implements the Model Context Protocol over stdio using JSON-RPC 2.0.
No external dependencies beyond context-fabrica itself.

Usage:
    context-fabrica-mcp --db ./memory.db
    context-fabrica-mcp --db ./memory.db --namespace myproject
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from .engine import DomainMemoryEngine
from .models import KnowledgeRecord

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "context-fabrica"
SERVER_VERSION = "0.5.0"

logging.basicConfig(level=logging.DEBUG, stream=sys.stderr, format="%(levelname)s: %(message)s")
log = logging.getLogger(SERVER_NAME)


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "remember",
            "description": (
                "Store a fact, observation, or piece of knowledge in long-term memory. "
                "Use this when you learn something worth recalling later: architectural decisions, "
                "code patterns, user preferences, debugging insights, or domain facts."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The knowledge to store"},
                    "source": {"type": "string", "description": "Where this came from (e.g. 'code-review', 'user', 'investigation')", "default": "agent"},
                    "domain": {"type": "string", "description": "Knowledge domain (e.g. 'auth', 'payments', 'infra')", "default": "global"},
                    "confidence": {"type": "number", "description": "How confident you are in this fact (0.0-1.0)", "default": 0.7, "minimum": 0.0, "maximum": 1.0},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags for categorization", "default": []},
                    "record_id": {"type": "string", "description": "Optional explicit ID for the record"},
                },
                "required": ["text"],
            },
        },
        {
            "name": "recall",
            "description": (
                "Search long-term memory for facts relevant to a query. Returns scored results "
                "with rationale explaining why each result matched. Use this before making "
                "assumptions — check if you already know something."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language query to search memory"},
                    "top_k": {"type": "integer", "description": "Maximum results to return", "default": 5, "minimum": 1, "maximum": 20},
                    "domain": {"type": "string", "description": "Filter to a specific domain"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "synthesize",
            "description": (
                "Combine multiple remembered facts into a single provenance-backed observation. "
                "Use this when you notice a pattern across several facts and want to record the "
                "insight explicitly."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "record_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "IDs of records to synthesize into an observation",
                        "minItems": 2,
                    },
                    "record_id": {"type": "string", "description": "Optional ID for the new observation"},
                },
                "required": ["record_ids"],
            },
        },
        {
            "name": "promote",
            "description": (
                "Promote a staged (draft) memory to canonical status after verification. "
                "Use this when you've confirmed a low-confidence observation is actually true."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "record_id": {"type": "string", "description": "ID of the record to promote"},
                },
                "required": ["record_id"],
            },
        },
        {
            "name": "invalidate",
            "description": (
                "Soft-delete a memory that is no longer valid. The record is kept for audit "
                "but excluded from future queries. Use this when you discover a fact is wrong."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "record_id": {"type": "string", "description": "ID of the record to invalidate"},
                    "reason": {"type": "string", "description": "Why this record is being invalidated", "default": "obsolete"},
                },
                "required": ["record_id"],
            },
        },
        {
            "name": "supersede",
            "description": (
                "Replace an existing memory with an updated version. The old record is "
                "invalidated and linked to the new one, preserving the correction chain. "
                "Use this when a fact needs updating rather than deletion."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "old_record_id": {"type": "string", "description": "ID of the record being replaced"},
                    "new_text": {"type": "string", "description": "The updated knowledge"},
                    "reason": {"type": "string", "description": "Why the old record is being replaced", "default": "updated"},
                    "confidence": {"type": "number", "description": "Confidence in the new fact (0.0-1.0)", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["old_record_id", "new_text"],
            },
        },
    ]


class ContextFabricaMCP:
    def __init__(self, engine: DomainMemoryEngine, namespace: str = "default") -> None:
        self._engine = engine
        self._namespace = namespace

    def handle_message(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method", "")
        request_id = msg.get("id")
        params = msg.get("params", {})

        # Notifications (no id) — no response needed
        if request_id is None:
            return None

        handler = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "ping": self._handle_ping,
        }.get(method)

        if handler is None:
            return _error(request_id, -32601, f"Method not found: {method}")

        try:
            result = handler(params)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except KeyError as exc:
            return _error(request_id, -32602, f"Record not found: {exc}")
        except Exception as exc:
            log.exception("Tool execution failed")
            return _error(request_id, -32603, str(exc))

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def _handle_ping(self, params: dict[str, Any]) -> dict[str, Any]:
        return {}

    def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"tools": _tool_definitions()}

    def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        args = params.get("arguments", {})

        dispatch = {
            "remember": self._tool_remember,
            "recall": self._tool_recall,
            "synthesize": self._tool_synthesize,
            "promote": self._tool_promote,
            "invalidate": self._tool_invalidate,
            "supersede": self._tool_supersede,
        }

        handler = dispatch.get(name)
        if handler is None:
            return _tool_error(f"Unknown tool: {name}")

        try:
            return handler(args)
        except KeyError as exc:
            return _tool_error(f"Record not found: {exc}")
        except Exception as exc:
            log.exception("Tool %s failed", name)
            return _tool_error(str(exc))

    # ── Tools ──

    def _tool_remember(self, args: dict[str, Any]) -> dict[str, Any]:
        record = self._engine.ingest(
            args["text"],
            source=args.get("source", "agent"),
            domain=args.get("domain", "global"),
            namespace=self._namespace,
            confidence=args.get("confidence", 0.7),
            tags=args.get("tags", []),
            record_id=args.get("record_id"),
        )
        return _tool_result(
            f"Stored as {record.record_id} (stage={record.stage}, kind={record.kind}, confidence={record.confidence:.2f})"
        )

    def _tool_recall(self, args: dict[str, Any]) -> dict[str, Any]:
        results = self._engine.query(
            args["query"],
            top_k=args.get("top_k", 5),
            domain=args.get("domain"),
            namespace=self._namespace,
        )
        if not results:
            return _tool_result("No relevant memories found.")

        lines: list[str] = []
        for i, hit in enumerate(results, 1):
            r = hit.record
            lines.append(
                f"{i}. [{r.record_id}] score={hit.score:.3f} "
                f"({','.join(hit.rationale)})\n"
                f"   source={r.source} domain={r.domain} confidence={r.confidence:.2f} "
                f"stage={r.stage}\n"
                f"   {r.text[:300]}"
            )
        return _tool_result("\n\n".join(lines))

    def _tool_synthesize(self, args: dict[str, Any]) -> dict[str, Any]:
        observation = self._engine.synthesize_observation(
            args["record_ids"],
            record_id=args.get("record_id"),
        )
        return _tool_result(
            f"Synthesized observation {observation.record_id}\n"
            f"  derived_from={observation.metadata['derived_from']}\n"
            f"  {observation.text[:300]}"
        )

    def _tool_promote(self, args: dict[str, Any]) -> dict[str, Any]:
        record = self._engine.promote_record(args["record_id"])
        return _tool_result(f"Promoted {record.record_id} to stage={record.stage}")

    def _tool_invalidate(self, args: dict[str, Any]) -> dict[str, Any]:
        self._engine.invalidate_record(
            args["record_id"],
            reason=args.get("reason", "obsolete"),
        )
        return _tool_result(f"Invalidated {args['record_id']}")

    def _tool_supersede(self, args: dict[str, Any]) -> dict[str, Any]:
        new = self._engine.supersede_record(
            args["old_record_id"],
            args["new_text"],
            reason=args.get("reason", "updated"),
            confidence=args.get("confidence"),
        )
        return _tool_result(
            f"Superseded {args['old_record_id']} with {new.record_id}\n"
            f"  {new.text[:300]}"
        )


# ── JSON-RPC helpers ──

def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _tool_error(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"Error: {text}"}], "isError": True}


# ── Entry point ──

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="context-fabrica MCP server")
    parser.add_argument("--db", default="./context-fabrica-memory.db", help="Path to SQLite database file")
    parser.add_argument("--namespace", default="default", help="Default namespace for this server instance")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    engine = DomainMemoryEngine()
    server = ContextFabricaMCP(engine, namespace=args.namespace)
    log.info("context-fabrica MCP server started (db=%s, namespace=%s)", args.db, args.namespace)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            log.warning("Ignoring malformed JSON: %s", line[:100])
            continue

        response = server.handle_message(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
