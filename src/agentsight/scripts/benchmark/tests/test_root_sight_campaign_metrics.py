from __future__ import annotations
import importlib
import sys
from pathlib import Path
import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "tests"))
sys.path.insert(0, str(BASE / "campaign"))
sys.path.insert(0, str(BASE / "single_run"))
campaign_evaluation = importlib.import_module("campaign_evaluation")
fixtures = importlib.import_module("test_benchmark")
complete_summary = fixtures.complete_summary
campaign_data = fixtures.campaign_data


@pytest.mark.parametrize("key", ["effective_qps", "http_success_rate", "drop_rate"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True])
def test_campaign_missing_invalid_numeric_metric(tmp_path, key, value):
    summary = complete_summary()
    summary[key] = value
    result = campaign_evaluation.evaluate(
        summary, campaign_data(tmp_path)["thresholds"]
    )
    assert result["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("key", ["process_survived", "runtime_clean"])
def test_campaign_boolean_requires_boolean(tmp_path, key):
    summary = complete_summary()
    summary[key] = 1
    result = campaign_evaluation.evaluate(
        summary, campaign_data(tmp_path)["thresholds"]
    )
    assert result["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("value", [10**1000, float("nan"), float("inf")])
def test_invalid_qps_is_missing_without_crashing(tmp_path, value):
    summary = complete_summary()
    summary["input_qps"] = value
    result = campaign_evaluation.evaluate(
        summary, campaign_data(tmp_path)["thresholds"]
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert "throughput_ratio" in result["missing"]


def test_overflowing_ratio_is_missing(tmp_path):
    summary = complete_summary(1e-308)
    summary["effective_qps"] = 1e308
    result = campaign_evaluation.evaluate(
        summary, campaign_data(tmp_path)["thresholds"]
    )
    assert result["verdict"] == "INCONCLUSIVE"


def test_real_failing_lifecycle_and_ordinary_measurements_keep_verdict(tmp_path):
    summary = complete_summary()
    thresholds = campaign_data(tmp_path)["thresholds"]
    assert campaign_evaluation.evaluate(summary, thresholds)["verdict"] == "PASS"
    summary["runtime_clean"] = False
    result = campaign_evaluation.evaluate(summary, thresholds)
    assert result["verdict"] == "FAIL" and result["failed"] == ["runtime_clean"]
