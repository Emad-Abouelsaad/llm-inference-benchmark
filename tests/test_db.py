"""Round-trip test against a real PostgreSQL. Skipped unless DATABASE_URL is set (CI sets it)."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from llmbench import db
from llmbench.client import RequestResult
from llmbench.metrics import summarize

DSN = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL not set")


def store_run(conn, model, started_at, ttft):
    results = [RequestResult(success=True, ttft_ms=ttft, e2e_ms=ttft + 900, output_tokens=10),
               RequestResult(success=False, error="timeout")]
    run_id, run_uuid = db.insert_run(
        conn, started_at=started_at, backend="test", model=model, base_url="http://x",
        max_tokens=10, git_sha=None, git_ref=None, ci_run_id=None,
        hardware={"cpu_model": "pytest"}, notes=None)
    db.insert_result(conn, run_id, summarize(results, 1.0, 1), results)
    db.finish_run(conn, run_id, started_at + timedelta(seconds=5))
    return run_uuid


def test_store_and_fetch_with_previous_run():
    model = f"pytest-{datetime.now().timestamp()}"
    now = datetime.now(timezone.utc)
    with db.connect(DSN) as conn:
        db.apply_schema(conn)
        old = store_run(conn, model, now - timedelta(hours=1), ttft=100)
        new = store_run(conn, model, now, ttft=200)

        run, results = db.fetch_run_results(conn, str(new))
        assert run["hardware"]["cpu_model"] == "pytest"
        assert results[0]["num_failed"] == 1
        assert results[0]["ttft_p50_ms"] == 200

        prev_run, prev_results = db.fetch_previous_run(conn, run)
        assert prev_run["run_uuid"] == old
        assert prev_results[0]["ttft_p50_ms"] == 100

        count = conn.execute(
            "SELECT count(*) FROM v_benchmark_summary WHERE model = %s", (model,)).fetchone()[0]
        assert count == 2
        conn.rollback()  # leave the database clean
