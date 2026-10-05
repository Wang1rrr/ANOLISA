import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
BENCHMARK = ROOT / "src/agentsight/scripts/benchmark"
sys.path.insert(0, str(BENCHMARK / "single_run"))
sys.path.insert(0, str(BENCHMARK / "campaign"))

config = importlib.import_module("campaign_config")


def campaign():
    return json.loads(
        (BENCHMARK / "campaign/campaign.example.json").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("section", ["capacity", "matrix"])
@pytest.mark.parametrize("value", [None, [], "bad", 1])
def test_section_shapes_report_validation_errors(section, value):
    value_config = campaign()
    value_config[section] = value
    with pytest.raises((TypeError, ValueError)) as error:
        config.validate_campaign(value_config)
    assert section in str(error.value)


@pytest.mark.parametrize("value", [None, "123", {}, [[1]], [1, 2, 3, 4, [5]]])
def test_matrix_levels_are_validated_before_counting(value):
    value_config = campaign()
    value_config["matrix"]["qps"] = value
    with pytest.raises((TypeError, ValueError)) as error:
        config.validate_campaign(value_config)
    assert "matrix.qps" in str(error.value)


def test_oversize_threshold_reports_validation_error():
    value_config = campaign()
    value_config["thresholds"]["max_rss_mb"] = 10**1000
    with pytest.raises(ValueError, match="thresholds.max_rss_mb"):
        config.validate_campaign(value_config)


@pytest.mark.parametrize("value", [False, True])
def test_tolerance_requires_a_number_not_boolean(value):
    value_config = campaign()
    value_config["recovery"]["tolerance_ratio"] = value
    with pytest.raises(ValueError, match="tolerance_ratio"):
        config.validate_campaign(value_config)


def test_example_campaign_is_valid():
    config.validate_campaign(campaign())
