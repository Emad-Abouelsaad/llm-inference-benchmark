"""Load generation: run N requests at a fixed concurrency and collect results."""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import platform
import time
from pathlib import Path

from .client import RequestResult, stream_chat


def load_prompts(path: Path) -> list[str]:
    prompts = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            prompts.append(json.loads(line)["prompt"])
    if not prompts:
        raise ValueError(f"no prompts found in {path}")
    return prompts


async def run_level(client, *, base_url: str, model: str, prompts: list[str], concurrency: int,
                    num_requests: int, max_tokens: int,
                    ignore_eos: bool) -> tuple[list[RequestResult], float]:
    """Closed-loop load: at most `concurrency` requests in flight until `num_requests` are done."""
    semaphore = asyncio.Semaphore(concurrency)
    prompt_cycle = itertools.cycle(prompts)

    async def one(prompt: str) -> RequestResult:
        async with semaphore:
            return await stream_chat(client, base_url, model, prompt, max_tokens, ignore_eos)

    start = time.perf_counter()
    results = await asyncio.gather(*(one(next(prompt_cycle)) for _ in range(num_requests)))
    return list(results), time.perf_counter() - start


def hardware_info() -> dict:
    info = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "runner": os.getenv("RUNNER_NAME"),
    }
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text().splitlines():
            if line.startswith("model name"):
                info["cpu_model"] = line.split(":", 1)[1].strip()
                break
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        first = meminfo.read_text().splitlines()[0]  # "MemTotal:  16384000 kB"
        info["mem_total_gb"] = round(int(first.split()[1]) / 1024 / 1024, 1)
    return info
