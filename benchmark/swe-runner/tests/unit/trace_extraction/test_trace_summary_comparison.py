# Copyright 2026 Alibaba Cloud
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Compare exported summary evidence without invoking agents or evaluation."""

import csv
import io
import json
import os
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from swe_runner.cli import app
from swe_runner.trace_extraction.export import _SUMMARY_COLUMNS
from swe_runner.trace_extraction.helpers import ExtractionError

HEADERS = {key: header for header, key in _SUMMARY_COLUMNS}
KEYS = ["instance_id", "execution_count", "avg_input_tokens", "avg_output_tokens", "avg_total_tokens", "avg_steps"]


def summary(path, rows, encoding="utf-8"):
    with path.open("w", encoding=encoding, newline="") as file:
        writer = csv.DictWriter(file, fieldnames=[HEADERS[key] for key in KEYS])
        writer.writeheader()
        for instance_id, count, input_tokens, output_tokens, steps in rows:
            values = [
                instance_id,
                count,
                input_tokens,
                output_tokens,
                Decimal(str(input_tokens)) + Decimal(str(output_tokens)),
                steps,
            ]
            writer.writerow({HEADERS[key]: value for key, value in zip(KEYS, values, strict=True)})
    return path


def compare(baseline, candidate, output):
    from swe_runner.trace_extraction.comparison import write_trace_comparison_csv

    return write_trace_comparison_csv(baseline, candidate, output)


def read_rows(output):
    with output.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def test_align_cases_and_compare_per_execution_means(tmp_path):
    baseline = summary(tmp_path / "baseline.csv", [("same", 1, 100, 20, 5), ("old", 2, 30, 10, 2)])
    candidate = summary(tmp_path / "candidate.csv", [("same", 4, 40, 10, 3), ("new", 3, 15, 5, 1)])
    originals = baseline.read_bytes(), candidate.read_bytes()
    output = tmp_path / "nested" / "comparison.csv"
    result = compare(baseline, candidate, output)
    rows = read_rows(output)
    assert [row["instance_id"] for row in rows] == ["new", "old", "same"]
    assert [row["status"] for row in rows] == ["candidate-only", "baseline-only", "matched"]
    row = rows[-1]
    assert row["baseline_executions"] == "1" and row["candidate_executions"] == "4"
    assert Decimal(row["delta_avg_input_tokens"]) == -60
    assert row["pct_delta_avg_input_tokens"] == "-60.00"
    assert Decimal(row["delta_avg_total_tokens"]) == -70
    assert row["pct_delta_avg_steps"] == "-40.00"
    assert rows[0]["baseline_avg_total_tokens"] == ""
    assert rows[1]["candidate_executions"] == ""
    assert rows[0]["delta_avg_steps"] == rows[1]["pct_delta_avg_steps"] == ""
    assert (result.matched_count, result.baseline_only_count, result.candidate_only_count) == (1, 1, 1)
    assert result.csv_path == output
    assert (baseline.read_bytes(), candidate.read_bytes()) == originals


def test_zero_baselines_have_explicit_percentage_semantics(tmp_path):
    baseline = summary(tmp_path / "base.csv", [("zero", 1, 0, 0, 0), ("positive", 1, 0, 0, 0)])
    candidate = summary(tmp_path / "cand.csv", [("zero", 1, 0, 0, 0), ("positive", 1, 10, 5, 2)])
    output = tmp_path / "result.csv"
    compare(baseline, candidate, output)
    rows = {row["instance_id"]: row for row in read_rows(output)}
    assert rows["zero"]["pct_delta_avg_total_tokens"] == "0.00"
    assert rows["positive"]["pct_delta_avg_total_tokens"] == ""
    assert Decimal(rows["positive"]["delta_avg_total_tokens"]) == 15
    assert "Infinity" not in output.read_text()


def test_unicode_quoted_ids_and_bom_are_preserved(tmp_path):
    instance_id = 'case,"\u00e9\U0001f600"\nline'
    baseline = summary(tmp_path / "base.csv", [(instance_id, 1, 10, 5, 2)], encoding="utf-8-sig")
    candidate = summary(tmp_path / "cand.csv", [(instance_id, 2, 9, 4, 1)])
    output = tmp_path / "result.csv"
    compare(baseline, candidate, output)
    assert read_rows(output)[0]["instance_id"] == instance_id
    assert not output.read_bytes().startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize(
    "mutate",
    [
        "duplicate-id",
        "empty-id",
        "negative-count",
        "zero-count",
        "fraction-count",
        "empty-metric",
        "invalid-metric",
        "nan",
        "infinity",
        "negative-metric",
        "overflow",
        "underflow",
        "missing-field",
        "extra-field",
        "duplicate-header",
        "missing-header",
        "bad-quote",
        "empty-file",
        "bad-encoding",
    ],
)
def test_invalid_inputs_are_rejected_before_output(tmp_path, mutate):
    baseline = summary(tmp_path / "base.csv", [("same", 1, 10, 5, 2)])
    candidate = summary(tmp_path / "cand.csv", [("same", 1, 9, 4, 1)])
    content = baseline.read_text(encoding="utf-8")
    rows = list(csv.reader(io.StringIO(content)))
    changes = {
        "empty-id": (0, ""),
        "negative-count": (1, "-1"),
        "zero-count": (1, "0"),
        "fraction-count": (1, "1.5"),
        "empty-metric": (2, ""),
        "invalid-metric": (2, "unknown"),
        "nan": (2, "NaN"),
        "infinity": (2, "Infinity"),
        "negative-metric": (2, "-1"),
        "overflow": (2, "1e9999"),
        "underflow": (2, "1e-9999"),
    }
    if mutate in changes:
        index, value = changes[mutate]
        rows[1][index] = value
    elif mutate == "duplicate-id":
        rows.append(rows[1])
    elif mutate == "missing-field":
        rows[1].pop()
    elif mutate == "extra-field":
        rows[1].append("extra")
    elif mutate == "duplicate-header":
        rows[0][1] = rows[0][0]
    elif mutate == "missing-header":
        rows[0][2] = "unexpected"
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(rows)
    baseline.write_text(buffer.getvalue(), encoding="utf-8")
    if mutate == "bad-quote":
        baseline.write_text(content.splitlines()[0] + '\n"unterminated', encoding="utf-8")
    elif mutate == "empty-file":
        baseline.write_text("", encoding="utf-8")
    elif mutate == "bad-encoding":
        baseline.write_bytes(b"\xff")
    output = tmp_path / "new" / "comparison.csv"
    with pytest.raises(ExtractionError):
        compare(baseline, candidate, output)
    assert not output.parent.exists()


def test_missing_input_does_not_replace_existing_output(tmp_path):
    candidate = summary(tmp_path / "cand.csv", [("same", 1, 9, 4, 1)])
    output = tmp_path / "comparison.csv"
    output.write_text("original report", encoding="utf-8")
    with pytest.raises(ExtractionError):
        compare(tmp_path / "missing.csv", candidate, output)
    assert output.read_text() == "original report"


@pytest.mark.parametrize("alias", ["same-path", "hardlink"])
def test_output_cannot_overwrite_input_alias(tmp_path, alias):
    baseline = summary(tmp_path / "base.csv", [("same", 1, 10, 5, 2)])
    candidate = summary(tmp_path / "cand.csv", [("same", 1, 9, 4, 1)])
    output = baseline if alias == "same-path" else tmp_path / "alias.csv"
    if alias == "hardlink":
        os.link(baseline, output)
    original = baseline.read_bytes()
    with pytest.raises(ExtractionError, match="input"):
        compare(baseline, candidate, output)
    assert baseline.read_bytes() == original


def test_failed_publication_preserves_output_and_cleans_owned_file(tmp_path, monkeypatch):
    from swe_runner.trace_extraction import comparison

    baseline = summary(tmp_path / "base.csv", [("same", 1, 10, 5, 2)])
    candidate = summary(tmp_path / "cand.csv", [("same", 1, 9, 4, 1)])
    output = tmp_path / "comparison.csv"
    output.write_text("original report", encoding="utf-8")

    def fail_replace(*_args):
        raise OSError("fixture write failure")

    monkeypatch.setattr(comparison.os, "replace", fail_replace)
    with pytest.raises(ExtractionError, match="fixture write failure"):
        compare(baseline, candidate, output)
    assert output.read_text() == "original report"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["base.csv", "cand.csv", "comparison.csv"]


def test_large_finite_values_do_not_overflow_percentage(tmp_path):
    baseline = summary(tmp_path / "base.csv", [("same", 1, "1e-300", 0, 1)])
    candidate = summary(tmp_path / "cand.csv", [("same", 1, "1e300", 0, 1)])
    output = tmp_path / "comparison.csv"
    compare(baseline, candidate, output)
    percentage = Decimal(read_rows(output)[0]["pct_delta_avg_input_tokens"])
    assert percentage.is_finite()
    assert percentage > Decimal("1e601")


def test_actual_cli_exports_comparison_under_command_directory(tmp_path):
    baseline = summary(tmp_path / "base.csv", [("same", 1, 10, 5, 2)])
    candidate = summary(tmp_path / "cand.csv", [("same", 1, 9, 4, 1)])
    result = CliRunner().invoke(
        app,
        [
            "compare-traces",
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--output",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Matched cases: 1" in result.output
    output = tmp_path / "out" / "compare-traces" / "trace_comparison.csv"
    assert read_rows(output)[0]["pct_delta_avg_total_tokens"] == "-13.33"


def test_cli_reports_invalid_input_without_traceback(tmp_path):
    invalid = tmp_path / "bad.csv"
    invalid.write_text("not a summary", encoding="utf-8")
    result = CliRunner().invoke(app, ["compare-traces", "--baseline", str(invalid), "--candidate", str(invalid)])
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "Traceback" not in result.output


def test_empty_baseline_is_a_valid_exported_population(tmp_path):
    baseline = summary(tmp_path / "base.csv", [])
    candidate = summary(tmp_path / "cand.csv", [("new", 1, 10, 5, 2)])
    output = tmp_path / "result.csv"
    result = compare(baseline, candidate, output)
    assert (result.matched_count, result.baseline_only_count, result.candidate_only_count) == (0, 0, 1)
    assert read_rows(output)[0]["delta_avg_total_tokens"] == ""


def test_large_absolute_difference_retains_small_baseline(tmp_path):
    baseline = summary(tmp_path / "base.csv", [("same", 1, 1, 0, 1)])
    candidate = summary(tmp_path / "cand.csv", [("same", 1, "1e300", 0, 1)])
    output = tmp_path / "result.csv"
    compare(baseline, candidate, output)
    assert Decimal(read_rows(output)[0]["delta_avg_input_tokens"]) == Decimal("9" * 300)


def test_consumes_actual_analysis_exports_with_extra_summary_fields(tmp_path):
    from swe_runner.trace_extraction.export import write_trace_analysis_csvs

    summaries = []
    for run, budgets in [("baseline", [(100, 20, 5)]), ("candidate", [(30, 10, 2), (50, 10, 4)])]:
        root = tmp_path / run / "traces"
        case = root / "same-case"
        case.mkdir(parents=True)
        for trial, (input_tokens, output_tokens, steps) in enumerate(budgets):
            (case / f"trace{trial}.json").write_text(
                json.dumps(
                    {
                        "session_id": f"trial-{trial}",
                        "total_input_tokens": input_tokens,
                        "total_output_tokens": output_tokens,
                        "total_steps": steps,
                    }
                ),
                encoding="utf-8",
            )
        _, exported = write_trace_analysis_csvs(root, tmp_path / run / "analysis")
        summaries.append(exported)
    output = tmp_path / "comparison.csv"
    compare(*summaries, output)
    row = read_rows(output)[0]
    assert row["baseline_executions"] == "1" and row["candidate_executions"] == "2"
    assert row["pct_delta_avg_input_tokens"] == "-60.00"
    assert Decimal(row["delta_avg_total_tokens"]) == -70
