from __future__ import annotations
import sqlite3
import importlib
import sys
from pathlib import Path
import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "tests"))
sys.path.insert(0, str(BASE / "campaign"))
sys.path.insert(0, str(BASE / "single_run"))
validate_results = importlib.import_module("validate_results")


@pytest.mark.parametrize(
    "filename",
    [
        "capture#1.sqlite",
        "capture?part.sqlite",
        "capture%20.sqlite",
        "capture space.sqlite",
    ],
)
def test_readonly_uri_preserves_literal_path(tmp_path, filename):
    if sys.platform == "win32" and "?" in filename:
        pytest.skip("Question marks are not legal Windows filenames")
    path = tmp_path / filename
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE token_records(request_id TEXT,input_tokens INTEGER,output_tokens INTEGER)"
        )
        db.execute("INSERT INTO token_records VALUES ('bench-1',2,3)")
    assert validate_results.load_captured(path) == {"bench-1": [("complete", 5)]}
    assert validate_results.load_captured_incremental(
        path, "bench-", None, 0, 0, set()
    )[0] == {"bench-1": [("complete", 5)]}
