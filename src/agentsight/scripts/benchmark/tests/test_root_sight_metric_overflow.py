from __future__ import annotations
import json
import importlib
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "tests"))
sys.path.insert(0, str(BASE / "campaign"))
sys.path.insert(0, str(BASE / "single_run"))
benchmark_stats = importlib.import_module("benchmark_stats")
render_report = importlib.import_module("render_report")


def test_oversize_metric_is_ignored():
    assert benchmark_stats.numeric(10**1000) is None
    assert benchmark_stats.numeric("4.5") == 4.5
    assert benchmark_stats.numeric(True) is None


def test_outlier_json_metric_does_not_abort_following_samples(tmp_path):
    path = tmp_path / "k6.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"metric": "benchmark_requests", "data": {"value": value}})
            for value in [10**1000, 3]
        )
    )
    result = render_report.summarize_load(path)
    assert result["requests"] == 3
