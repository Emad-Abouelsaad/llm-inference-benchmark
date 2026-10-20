"""Aggregation of per-request results into benchmark statistics."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .client import RequestResult


def percentile(values: Sequence[float], pct: float) -> float | None:
    """Percentile with linear interpolation (same as numpy's default)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct / 100
    low, high = math.floor(rank), math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(results: Sequence[RequestResult], duration_s: float, concurrency: int) -> dict:
    ok = [r for r in results if r.success]
    ttft = [r.ttft_ms for r in ok if r.ttft_ms is not None]
    tpot = [t for t in (r.tpot_ms for r in ok) if t is not None]
    e2e = [r.e2e_ms for r in ok if r.e2e_ms is not None]
    total_tokens = sum(r.output_tokens for r in ok)

    return {
        "concurrency": concurrency,
        "num_requests": len(results),
        "num_failed": len(results) - len(ok),
        "duration_s": duration_s,
        "request_throughput": len(ok) / duration_s if duration_s > 0 else None,
        "output_token_throughput": total_tokens / duration_s if duration_s > 0 else None,
        "total_output_tokens": total_tokens,
        "ttft_mean_ms": mean(ttft),
        "ttft_p50_ms": percentile(ttft, 50),
        "ttft_p90_ms": percentile(ttft, 90),
        "ttft_p99_ms": percentile(ttft, 99),
        "tpot_mean_ms": mean(tpot),
        "tpot_p50_ms": percentile(tpot, 50),
        "tpot_p99_ms": percentile(tpot, 99),
        "e2e_mean_ms": mean(e2e),
        "e2e_p50_ms": percentile(e2e, 50),
        "e2e_p99_ms": percentile(e2e, 99),
    }
