from __future__ import annotations
import json
import importlib
import sys
from pathlib import Path
import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "tests"))
sys.path.insert(0, str(BASE / "campaign"))
sys.path.insert(0, str(BASE / "single_run"))
validate_results = importlib.import_module("validate_results")


@pytest.mark.parametrize("data", [None, [], 42, "bad", {"tags": []}])
def test_request_loader_ignores_invalid_point_shape(tmp_path, data):
    path = tmp_path / "load.jsonl"
    path.write_text(
        json.dumps({"data": data})
        + "\n"
        + json.dumps({"request_id": "ok", "data": {"status": 200}})
        + "\n"
    )
    assert validate_results.load_expected(path) == ({"ok"}, {"ok"})


@pytest.mark.parametrize("status", ["not-a-status", [], {}, float("inf")])
def test_invalid_status_keeps_request_and_following_valid_evidence(tmp_path, status):
    path = tmp_path / "k6.jsonl"
    path.write_text(
        json.dumps({"request_id": "bad", "data": {"status": status}})
        + "\n"
        + json.dumps({"request_id": "good", "data": {"status": "201"}})
    )
    assert validate_results.load_expected(path) == ({"bad", "good"}, {"good"})


def test_invalid_tags_do_not_hide_valid_top_level_request_id(tmp_path):
    path = tmp_path / "k6.jsonl"
    path.write_text(
        json.dumps({"request_id": "good", "data": {"tags": [], "status": 200}})
    )
    assert validate_results.load_expected(path) == ({"good"}, {"good"})
