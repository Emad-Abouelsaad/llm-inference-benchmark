import pytest

from llmbench.client import RequestResult
from llmbench.metrics import percentile, summarize


def test_percentile_interpolates_like_numpy():
    values = [10, 20, 30, 40]
    assert percentile(values, 50) == 25
    assert percentile(values, 0) == 10
    assert percentile(values, 100) == 40
    assert percentile(values, 90) == pytest.approx(37)


def test_percentile_empty():
    assert percentile([], 50) is None


def test_tpot_excludes_first_token():
    r = RequestResult(success=True, ttft_ms=100, e2e_ms=1100, output_tokens=11)
    assert r.tpot_ms == pytest.approx(100)


def test_tpot_undefined_for_single_token():
    assert RequestResult(success=True, ttft_ms=50, e2e_ms=50, output_tokens=1).tpot_ms is None


def test_summarize_counts_failures_and_throughput():
    results = [
        RequestResult(success=True, ttft_ms=100, e2e_ms=1000, output_tokens=10),
        RequestResult(success=True, ttft_ms=200, e2e_ms=2000, output_tokens=30),
        RequestResult(success=False, error="boom"),
    ]
    s = summarize(results, duration_s=2.0, concurrency=2)
    assert s["num_requests"] == 3
    assert s["num_failed"] == 1
    assert s["total_output_tokens"] == 40
    assert s["output_token_throughput"] == 20
    assert s["request_throughput"] == 1
    assert s["ttft_p50_ms"] == 150
