"""Command line entry point.

    python -m llmbench run    --base-url http://localhost:8000/v3 --model tinyllama ...
    python -m llmbench report --summary-file "$GITHUB_STEP_SUMMARY" --plot results/chart.png
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import db
from .client import wait_until_ready
from .metrics import summarize
from .report import plot, render_markdown
from .runner import hardware_info, load_prompts, run_level

DEFAULT_DSN = "postgresql://bench:bench@localhost:5432/bench"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="llmbench", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", DEFAULT_DSN))
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="benchmark a server and store results")
    run.add_argument("--base-url", required=True,
                     help="OpenAI-compatible base URL, e.g. http://localhost:8000/v3 (OVMS) "
                          "or http://localhost:8000/v1 (vLLM)")
    run.add_argument("--model", required=True, help="model name as served by the backend")
    run.add_argument("--backend", default="openvino", help="label stored with the run")
    run.add_argument("--concurrency", default="1,2,4",
                     help="comma-separated concurrency levels to sweep")
    run.add_argument("--num-requests", type=int, default=16, help="requests per level")
    run.add_argument("--max-tokens", type=int, default=128)
    run.add_argument("--warmup", type=int, default=2, help="untimed warmup requests")
    run.add_argument("--ignore-eos", action="store_true",
                     help="ask the server to always generate max_tokens (fixed output length)")
    run.add_argument("--prompts", type=Path, default=Path("prompts/prompts.jsonl"))
    run.add_argument("--request-timeout", type=float, default=600)
    run.add_argument("--wait-timeout", type=float, default=900,
                     help="seconds to wait for the server to come up")
    run.add_argument("--notes", default=None)
    run.add_argument("--json-out", type=Path, default=Path("results/results.json"))

    rep = sub.add_parser("report", help="render the latest (or given) run as markdown")
    rep.add_argument("--run-uuid", default=None)
    rep.add_argument("--summary-file", type=Path, default=None,
                     help="append markdown here (e.g. $GITHUB_STEP_SUMMARY); prints otherwise")
    rep.add_argument("--plot", type=Path, default=None, help="write a PNG chart here")
    return parser.parse_args(argv)


async def cmd_run(args: argparse.Namespace) -> int:
    levels = [int(c) for c in args.concurrency.split(",") if c.strip()]
    prompts = load_prompts(args.prompts)
    timeout = httpx.Timeout(args.request_timeout, connect=10)
    limits = httpx.Limits(max_connections=max(levels) + 4)

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        print(f"Waiting for {args.base_url} (model={args.model}) ...", flush=True)
        await wait_until_ready(client, args.base_url, args.model, args.wait_timeout)
        print("Server ready. Warming up ...", flush=True)
        await run_level(client, base_url=args.base_url, model=args.model, prompts=prompts,
                        concurrency=1, num_requests=args.warmup, max_tokens=args.max_tokens,
                        ignore_eos=args.ignore_eos)

        started_at = datetime.now(timezone.utc)
        levels_out = []
        for c in levels:
            results, duration = await run_level(
                client, base_url=args.base_url, model=args.model, prompts=prompts,
                concurrency=c, num_requests=args.num_requests, max_tokens=args.max_tokens,
                ignore_eos=args.ignore_eos)
            summary = summarize(results, duration, c)
            levels_out.append((summary, results))
            print(f"concurrency={c:>3}  ok={summary['num_requests'] - summary['num_failed']}"
                  f"/{summary['num_requests']}  "
                  f"tok/s={summary['output_token_throughput'] or 0:8.1f}  "
                  f"TTFT p50={summary['ttft_p50_ms'] or 0:8.1f} ms  "
                  f"TPOT p50={summary['tpot_p50_ms'] or 0:6.1f} ms", flush=True)
            for err in {r.error for r in results if r.error}:
                print(f"  error: {err}", file=sys.stderr)

    with db.connect(args.database_url) as conn:
        db.apply_schema(conn)
        run_id, run_uuid = db.insert_run(
            conn, started_at=started_at, backend=args.backend, model=args.model,
            base_url=args.base_url, max_tokens=args.max_tokens,
            git_sha=os.getenv("GITHUB_SHA"), git_ref=os.getenv("GITHUB_REF_NAME"),
            ci_run_id=os.getenv("GITHUB_RUN_ID"), hardware=hardware_info(), notes=args.notes)
        for summary, results in levels_out:
            db.insert_result(conn, run_id, summary, results)
        db.finish_run(conn, run_id, datetime.now(timezone.utc))
        conn.commit()
    print(f"Stored run {run_uuid} in PostgreSQL.")

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(
        {"run_uuid": str(run_uuid), "backend": args.backend, "model": args.model,
         "results": [s for s, _ in levels_out]}, indent=2))

    total = sum(s["num_requests"] for s, _ in levels_out)
    failed = sum(s["num_failed"] for s, _ in levels_out)
    return 1 if failed == total else 0


def cmd_report(args: argparse.Namespace) -> int:
    with db.connect(args.database_url) as conn:
        run, results = db.fetch_run_results(conn, args.run_uuid)
        previous = db.fetch_previous_run(conn, run)
    markdown = render_markdown(run, results, previous)
    if args.summary_file:
        with args.summary_file.open("a", encoding="utf-8") as fh:
            fh.write(markdown)
    else:
        print(markdown)
    if args.plot:
        plot(results, f"{run['backend']} · {run['model']}", args.plot)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "run":
        return asyncio.run(cmd_run(args))
    return cmd_report(args)


if __name__ == "__main__":
    sys.exit(main())
