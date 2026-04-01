import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "project_memory.py"


def test_project_memory_bootstrap_and_status(tmp_path: Path) -> None:
    bootstrap = subprocess.run(
        [sys.executable, str(SCRIPT), "bootstrap", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(bootstrap.stdout)
    assert payload["status"] == "bootstrapped"

    status = subprocess.run(
        [sys.executable, str(SCRIPT), "status", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    status_payload = json.loads(status.stdout)
    assert status_payload["counts"] == {"staging": 0, "canonical": 0, "patterns": 0}
