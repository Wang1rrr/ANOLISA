"""Apply frozen benchmark thresholds without treating missing data as success."""

from __future__ import annotations

import math
from typing import Any


def metric(
    summary: dict[str, Any], *keys: str, boolean: bool = False
) -> float | bool | None:
    """Read a finite numeric measurement or an exact boolean gate."""
    value: Any = summary
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if boolean:
        return value if isinstance(value, bool) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def evaluate(
    summary: dict[str, Any], thresholds: dict[str, float], scenario: str = "capacity"
) -> dict[str, Any]:
    """Apply frozen capacity gates, treating missing measurements as inconclusive."""
    input_qps = metric(summary, "input_qps")
    effective_qps = metric(summary, "effective_qps")
    ratio = (
        effective_qps / input_qps
        if input_qps is not None and input_qps > 0 and effective_qps is not None
        else None
    )
    if ratio is not None and not math.isfinite(ratio):
        ratio = None
    checks = {
        "throughput_ratio": (
            ratio,
            ">=",
            thresholds["min_throughput_ratio"],
        ),
        "http_success_rate": (
            metric(summary, "http_success_rate"),
            ">=",
            thresholds["min_http_success_rate"],
        ),
        "trace_completeness": (
            metric(summary, "trace_completeness"),
            ">=",
            thresholds["min_trace_completeness"],
        ),
        "token_accuracy": (
            metric(summary, "token_accuracy"),
            ">=",
            thresholds["min_token_accuracy"],
        ),
        "latency_p99_ms": (
            metric(summary, "latency_ms", "p99"),
            "<=",
            thresholds["max_p99_ms"],
        ),
        "drop_rate": (
            metric(summary, "drop_rate"),
            "<=",
            thresholds["max_drop_rate"],
        ),
        "rss_max_mb": (
            metric(summary, "resources", "rss_mb", "max"),
            "<=",
            thresholds["max_rss_mb"],
        ),
        "process_survived": (
            metric(summary, "process_survived", boolean=True),
            "==",
            True,
        ),
        "runtime_clean": (metric(summary, "runtime_clean", boolean=True), "==", True),
    }
    if scenario == "soak":
        checks["rss_slope_mb_per_hour"] = (
            metric(summary, "resources", "rss_mb", "slope_per_hour"),
            "<=",
            thresholds["max_rss_slope_mb_per_hour"],
        )
    if scenario == "soak":
        checks.update(
            {
                "fd_slope_per_hour": (
                    metric(summary, "resources", "file_descriptors", "slope_per_hour"),
                    "<=",
                    thresholds["max_fd_slope_per_hour"],
                ),
                "thread_slope_per_hour": (
                    metric(summary, "resources", "threads", "slope_per_hour"),
                    "<=",
                    thresholds["max_thread_slope_per_hour"],
                ),
                "socket_slope_per_hour": (
                    metric(
                        summary, "resources", "active_connections", "slope_per_hour"
                    ),
                    "<=",
                    thresholds["max_socket_slope_per_hour"],
                ),
            }
        )
    missing = [name for name, (value, _, _) in checks.items() if value is None]
    failed = []
    for name, (value, operator, expected) in checks.items():
        if value is None:
            continue
        passed = (
            value >= expected
            if operator == ">="
            else value <= expected
            if operator == "<="
            else value == expected
        )
        if not passed:
            failed.append(name)
    verdict = "INCONCLUSIVE" if missing else "FAIL" if failed else "PASS"
    return {"verdict": verdict, "checks": checks, "missing": missing, "failed": failed}
