"""Markdown report (for the GitHub Actions job summary) and charts."""

from __future__ import annotations

from pathlib import Path


def _fmt(value, digits: int = 1) -> str:
    return "–" if value is None else f"{value:,.{digits}f}"


def _delta(new, old, lower_is_better: bool) -> str:
    if new is None or old in (None, 0):
        return ""
    change = (new - old) / old * 100
    better = change < 0 if lower_is_better else change > 0
    icon = "🟢" if better else ("🔴" if abs(change) >= 5 else "⚪")
    return f" {icon} {change:+.0f}%"


def render_markdown(run: dict, results: list[dict], previous: tuple[dict, list] | None) -> str:
    hw = run.get("hardware") or {}
    prev_by_c = {r["concurrency"]: r for r in previous[1]} if previous else {}

    lines = [
        "## LLM inference benchmark",
        "",
        f"- **Backend:** `{run['backend']}`  **Model:** `{run['model']}`",
        f"- **Max output tokens:** {run['max_tokens']}"
        f"  **Commit:** `{(run.get('git_sha') or '')[:7]}`",
        f"- **Hardware:** {hw.get('cpu_model', 'unknown CPU')} · {hw.get('cpu_count')} vCPU"
        f" · {hw.get('mem_total_gb', '?')} GB RAM",
        f"- **Run:** `{run['run_uuid']}` at {run['started_at']:%Y-%m-%d %H:%M UTC}",
        "",
        "| Concurrency | Requests (failed) | Output tok/s | Req/s | TTFT p50 (ms) | TTFT p99 (ms)"
        " | TPOT p50 (ms) | E2E p50 (ms) |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        p = prev_by_c.get(r["concurrency"], {})
        lines.append(
            f"| {r['concurrency']} | {r['num_requests']} ({r['num_failed']})"
            f" | {_fmt(r['output_token_throughput'])}"
            f"{_delta(r['output_token_throughput'], p.get('output_token_throughput'), False)}"
            f" | {_fmt(r['request_throughput'], 2)}"
            f" | {_fmt(r['ttft_p50_ms'])}{_delta(r['ttft_p50_ms'], p.get('ttft_p50_ms'), True)}"
            f" | {_fmt(r['ttft_p99_ms'])}"
            f" | {_fmt(r['tpot_p50_ms'])}{_delta(r['tpot_p50_ms'], p.get('tpot_p50_ms'), True)}"
            f" | {_fmt(r['e2e_p50_ms'])} |"
        )
    if previous:
        lines += ["", f"_Deltas compared with previous run `{previous[0]['run_uuid']}`._"]
    lines += [
        "",
        "**TTFT** = time to first token · **TPOT** = time per output token after the first"
        " · **Output tok/s** = total generated tokens / wall time across all concurrent requests",
        "",
    ]
    return "\n".join(lines)


def plot(results: list[dict], title: str, out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    conc = [r["concurrency"] for r in results]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
    ax1.plot(conc, [r["output_token_throughput"] for r in results], marker="o")
    ax1.set(title="Output throughput", xlabel="Concurrent requests", ylabel="tokens / s")
    ax2.plot(conc, [r["ttft_p50_ms"] for r in results], marker="o", label="p50")
    ax2.plot(conc, [r["ttft_p99_ms"] for r in results], marker="o", label="p99")
    ax2.set(title="Time to first token", xlabel="Concurrent requests", ylabel="ms")
    ax2.legend()
    for ax in (ax1, ax2):
        ax.grid(alpha=0.3)
        ax.set_xticks(conc)
    fig.suptitle(title)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
