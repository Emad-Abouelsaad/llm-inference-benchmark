"""PostgreSQL persistence for benchmark runs."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .client import RequestResult

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"

RESULT_COLUMNS = (
    "concurrency", "num_requests", "num_failed", "duration_s", "request_throughput",
    "output_token_throughput", "total_output_tokens", "ttft_mean_ms", "ttft_p50_ms",
    "ttft_p90_ms", "ttft_p99_ms", "tpot_mean_ms", "tpot_p50_ms", "tpot_p99_ms",
    "e2e_mean_ms", "e2e_p50_ms", "e2e_p99_ms",
)


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, autocommit=False)


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def insert_run(conn: psycopg.Connection, *, started_at: datetime, backend: str, model: str,
               base_url: str, max_tokens: int, git_sha: str | None, git_ref: str | None,
               ci_run_id: str | None, hardware: dict, notes: str | None) -> tuple[int, uuid.UUID]:
    run_uuid = uuid.uuid4()
    row = conn.execute(
        """
        INSERT INTO benchmark_runs
            (run_uuid, started_at, backend, model, base_url, max_tokens,
             git_sha, git_ref, ci_run_id, hardware, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (run_uuid, started_at, backend, model, base_url, max_tokens,
         git_sha, git_ref, ci_run_id, Jsonb(hardware), notes),
    ).fetchone()
    return row[0], run_uuid


def insert_result(conn: psycopg.Connection, run_id: int, summary: dict,
                  requests: list[RequestResult]) -> int:
    cols = ", ".join(RESULT_COLUMNS)
    placeholders = ", ".join(["%s"] * (len(RESULT_COLUMNS) + 1))
    result_id = conn.execute(
        f"INSERT INTO benchmark_results (run_id, {cols}) VALUES ({placeholders}) RETURNING id",
        (run_id, *(summary[c] for c in RESULT_COLUMNS)),
    ).fetchone()[0]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO request_metrics
                (result_id, success, ttft_ms, tpot_ms, e2e_ms, prompt_tokens, output_tokens, error)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [(result_id, r.success, r.ttft_ms, r.tpot_ms, r.e2e_ms, r.prompt_tokens,
              r.output_tokens, r.error) for r in requests],
        )
    return result_id


def finish_run(conn: psycopg.Connection, run_id: int, finished_at: datetime) -> None:
    conn.execute("UPDATE benchmark_runs SET finished_at = %s WHERE id = %s", (finished_at, run_id))


def fetch_run_results(conn: psycopg.Connection, run_uuid: str | None = None) -> tuple[dict, list]:
    """Return (run, results) for the given run, or for the latest run when run_uuid is None."""
    with conn.cursor(row_factory=dict_row) as cur:
        if run_uuid:
            cur.execute("SELECT * FROM benchmark_runs WHERE run_uuid = %s", (run_uuid,))
        else:
            cur.execute("SELECT * FROM benchmark_runs ORDER BY started_at DESC LIMIT 1")
        run = cur.fetchone()
        if run is None:
            raise LookupError("no benchmark run found")
        cur.execute(
            "SELECT * FROM benchmark_results WHERE run_id = %s ORDER BY concurrency", (run["id"],)
        )
        return run, cur.fetchall()


def fetch_previous_run(conn: psycopg.Connection, run: dict) -> tuple[dict, list] | None:
    """Most recent earlier run with the same backend and model, for regression comparison."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT run_uuid FROM benchmark_runs
            WHERE backend = %s AND model = %s AND started_at < %s AND finished_at IS NOT NULL
            ORDER BY started_at DESC LIMIT 1
            """,
            (run["backend"], run["model"], run["started_at"]),
        )
        row = cur.fetchone()
    return fetch_run_results(conn, str(row["run_uuid"])) if row else None
