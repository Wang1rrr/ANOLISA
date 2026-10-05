from __future__ import annotations
import importlib
import sys
from pathlib import Path


import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "tests"))
sys.path.insert(0, str(BASE / "campaign"))
sys.path.insert(0, str(BASE / "single_run"))
render_report = importlib.import_module("render_report")


def test_counter_reset_counts_new_epoch():
    assert render_report.counter_delta([10, 13, 2, 5]) == 8
    assert render_report.counter_delta([0, 3, 0, 2]) == 5
    assert render_report.counter_delta([10, 13, 15]) == 5


def test_drop_summary_counts_both_counter_epochs(tmp_path):
    path = tmp_path / "metrics.csv"
    path.write_text(
        "ring_buffer_dropped,channel_dropped,completed\n10,5,100\n13,7,110\n2,1,4\n5,2,10\n"
    )
    summary = render_report.summarize_drops(path, 100)
    assert summary["ring_buffer_dropped"] == 8
    assert summary["channel_dropped"] == 4
    assert summary["completed"] == 20
    assert summary["drop_rate"] == pytest.approx(37.5)
