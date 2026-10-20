from datetime import datetime, timezone

from llmbench.report import render_markdown


def row(concurrency, tok_s, ttft):
    return {
        "concurrency": concurrency, "num_requests": 8, "num_failed": 0,
        "output_token_throughput": tok_s, "request_throughput": 1.0,
        "ttft_p50_ms": ttft, "ttft_p99_ms": ttft * 2, "tpot_p50_ms": 40.0, "e2e_p50_ms": 900.0,
    }


RUN = {
    "run_uuid": "abc", "backend": "openvino", "model": "tiny", "max_tokens": 64,
    "git_sha": "0123456789", "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    "hardware": {"cpu_model": "Test CPU", "cpu_count": 4, "mem_total_gb": 16},
}


def test_report_contains_table_rows():
    md = render_markdown(RUN, [row(1, 25.0, 300.0), row(4, 60.0, 900.0)], previous=None)
    assert "| 1 | 8 (0) | 25.0 |" in md
    assert "| 4 | 8 (0) | 60.0 |" in md
    assert "Test CPU" in md


def test_report_shows_regression_against_previous_run():
    previous = ({**RUN, "run_uuid": "old"}, [row(1, 50.0, 300.0)])
    md = render_markdown(RUN, [row(1, 25.0, 300.0)], previous)
    assert "🔴 -50%" in md
    assert "`old`" in md
