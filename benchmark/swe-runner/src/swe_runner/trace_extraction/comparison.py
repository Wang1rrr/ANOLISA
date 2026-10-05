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

"""Offline case alignment and budget comparison for exported trace summaries."""

import csv
import logging
import math
import os
from dataclasses import dataclass
from decimal import Decimal, DecimalException, localcontext
from pathlib import Path
from tempfile import NamedTemporaryFile

from swe_runner.trace_extraction.export import _SUMMARY_COLUMNS
from swe_runner.trace_extraction.helpers import ExtractionError

logger = logging.getLogger(__name__)
_HEADERS = {key: header for header, key in _SUMMARY_COLUMNS}
_METRICS = ("avg_input_tokens", "avg_output_tokens", "avg_total_tokens", "avg_steps")
_REQUIRED_KEYS = ("instance_id", "execution_count", *_METRICS)
_COMPARISON_COLUMNS = (
    "instance_id",
    "status",
    "baseline_executions",
    "candidate_executions",
    *(f"{prefix}_{metric}" for metric in _METRICS for prefix in ("baseline", "candidate", "delta", "pct_delta")),
)


@dataclass(frozen=True)
class _Summary:
    execution_count: int
    metrics: dict[str, Decimal]


@dataclass(frozen=True)
class TraceComparisonResult:
    """Comparison artifact and the sizes of its three case populations."""

    csv_path: Path
    matched_count: int
    baseline_only_count: int
    candidate_only_count: int


def _parse_metric(value: str, path: Path, line: int, key: str) -> Decimal:
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0:
            raise ValueError
        numeric = float(number)
        if not math.isfinite(numeric) or (number != 0 and numeric == 0):
            raise ValueError
    except (DecimalException, ValueError, OverflowError) as error:
        raise ExtractionError(f"Invalid nonnegative finite {key} in {path} at CSV line {line}") from error
    return number if number != 0 else Decimal(0)


def _read_summary(path: Path) -> dict[str, _Summary]:
    summaries: dict[str, _Summary] = {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file, strict=True)
            headers = reader.fieldnames
            if not headers or len(headers) != len(set(headers)):
                raise ExtractionError(f"Missing or duplicate summary CSV headers in {path}")
            missing = [key for key in _REQUIRED_KEYS if _HEADERS[key] not in headers]
            if missing:
                raise ExtractionError(f"Missing summary fields in {path}: {', '.join(missing)}")
            for row in reader:
                if None in row or any(row.get(_HEADERS[key]) is None for key in _REQUIRED_KEYS):
                    raise ExtractionError(f"Malformed summary row in {path} at CSV line {reader.line_num}")
                instance_id = row[_HEADERS["instance_id"]]
                if not instance_id.strip() or instance_id in summaries:
                    raise ExtractionError(f"Empty or duplicate instance ID in {path} at CSV line {reader.line_num}")
                try:
                    execution_count = int(row[_HEADERS["execution_count"]])
                    if execution_count <= 0:
                        raise ValueError
                except ValueError as error:
                    raise ExtractionError(
                        f"Invalid positive execution_count in {path} at CSV line {reader.line_num}"
                    ) from error
                metrics = {key: _parse_metric(row[_HEADERS[key]], path, reader.line_num, key) for key in _METRICS}
                summaries[instance_id] = _Summary(execution_count, metrics)
    except (OSError, UnicodeError, csv.Error) as error:
        raise ExtractionError(f"Cannot read trace summary {path}: {error}") from error
    return summaries


def _comparison_rows(
    baseline: dict[str, _Summary], candidate: dict[str, _Summary]
) -> tuple[list[dict[str, str | int]], dict[str, int]]:
    rows: list[dict[str, str | int]] = []
    counts = {"matched": 0, "baseline-only": 0, "candidate-only": 0}
    # Float-sized exported means span fewer than 650 decimal places, including
    # subnormal values. Keep enough precision for exact absolute differences
    # and two-decimal percentages without overflowing intermediate arithmetic.
    with localcontext() as context:
        context.prec = 700
        for instance_id in sorted(baseline.keys() | candidate.keys()):
            left = baseline.get(instance_id)
            right = candidate.get(instance_id)
            status = "matched" if left and right else "baseline-only" if left else "candidate-only"
            counts[status] += 1
            row: dict[str, str | int] = dict.fromkeys(_COMPARISON_COLUMNS, "")
            row.update(
                {
                    "instance_id": instance_id,
                    "status": status,
                    "baseline_executions": left.execution_count if left else "",
                    "candidate_executions": right.execution_count if right else "",
                }
            )
            for metric in _METRICS:
                if left:
                    row[f"baseline_{metric}"] = format(left.metrics[metric], "f")
                if right:
                    row[f"candidate_{metric}"] = format(right.metrics[metric], "f")
                if left and right:
                    old, new = left.metrics[metric], right.metrics[metric]
                    delta = new - old
                    row[f"delta_{metric}"] = format(delta, "f")
                    if old:
                        row[f"pct_delta_{metric}"] = format(delta / old * 100, ".2f")
                    elif not new:
                        row[f"pct_delta_{metric}"] = "0.00"
            rows.append(row)
    return rows, counts


def write_trace_comparison_csv(
    baseline_summary: str | Path, candidate_summary: str | Path, output_csv: str | Path
) -> TraceComparisonResult:
    """Align two summary CSVs and publish complete UTF-8 comparison evidence."""
    baseline_path = Path(baseline_summary)
    candidate_path = Path(candidate_summary)
    output_path = Path(output_csv)
    baseline = _read_summary(baseline_path)
    candidate = _read_summary(candidate_path)
    try:
        for input_path in (baseline_path, candidate_path):
            if output_path.resolve() == input_path.resolve() or (
                output_path.exists() and output_path.samefile(input_path)
            ):
                raise ExtractionError("Comparison output must not overwrite an input summary")
        rows, counts = _comparison_rows(baseline, candidate)
    except (OSError, DecimalException) as error:
        raise ExtractionError(f"Cannot compare trace summaries: {error}") from error

    temporary = None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            writer = csv.DictWriter(file, fieldnames=_COMPARISON_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, output_path)
    except OSError as error:
        raise ExtractionError(f"Cannot publish trace comparison {output_path}: {error}") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.warning("Cannot remove comparison temporary file %s", temporary, exc_info=True)
    return TraceComparisonResult(output_path, counts["matched"], counts["baseline-only"], counts["candidate-only"])
