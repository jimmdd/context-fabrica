from src.context_fabrica.models import KnowledgeRecord
from src.context_fabrica.policy import decide_memory_tier, promote_record


def test_policy_routes_patterns_into_pattern_tier() -> None:
    record = KnowledgeRecord(
        record_id="p1",
        text="Reusable deployment pattern for auth rollouts.",
        source="pattern-miner",
        tags=["pattern"],
    )

    decision = decide_memory_tier(record)
    assert decision.stage == "pattern"
    assert decision.kind == "pattern"


def test_policy_routes_low_confidence_notes_into_staging() -> None:
    record = KnowledgeRecord(
        record_id="n1",
        text="Draft TODO for service ownership cleanup.",
        source="scratchpad",
        confidence=0.3,
    )

    decision = decide_memory_tier(record)
    assert decision.stage == "staged"
    assert decision.kind == "note"


def test_promote_record_marks_reviewed() -> None:
    record = KnowledgeRecord(record_id="n2", text="wip", stage="staged", kind="note")
    promote_record(record)
    assert record.stage == "canonical"
    assert record.kind == "fact"
    assert record.reviewed_at is not None
