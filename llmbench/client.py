"""Streaming client for OpenAI-compatible chat completion endpoints.

Works with vLLM (`/v1`) and OpenVINO Model Server (`/v3`) since both speak the same
Server-Sent Events protocol.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass


@dataclass
class RequestResult:
    success: bool
    ttft_ms: float | None = None
    e2e_ms: float | None = None
    prompt_tokens: int | None = None
    output_tokens: int = 0
    error: str | None = None

    @property
    def tpot_ms(self) -> float | None:
        """Time per output token after the first one (a.k.a. inter-token latency)."""
        if not self.success or self.ttft_ms is None or self.e2e_ms is None:
            return None
        if self.output_tokens < 2:
            return None
        return (self.e2e_ms - self.ttft_ms) / (self.output_tokens - 1)


def build_payload(
    model: str, prompt: str, max_tokens: int, ignore_eos: bool = False
) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if ignore_eos:
        payload["ignore_eos"] = True
    return payload


async def stream_chat(
    client,
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    ignore_eos: bool = False,
) -> RequestResult:
    """Send one streaming request and time the first and last content chunks."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = build_payload(model, prompt, max_tokens, ignore_eos)

    start = time.perf_counter()
    ttft: float | None = None
    chunks = 0
    usage: dict | None = None
    try:
        async with client.stream("POST", url, json=payload) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")[:500]
                return RequestResult(success=False, error=f"HTTP {resp.status_code}: {body}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if event.get("usage"):
                    usage = event["usage"]
                for choice in event.get("choices") or []:
                    if (choice.get("delta") or {}).get("content"):
                        if ttft is None:
                            ttft = time.perf_counter() - start
                        chunks += 1
    except Exception as exc:  # network errors, timeouts, malformed JSON from the server
        return RequestResult(success=False, error=f"{type(exc).__name__}: {exc}")

    e2e = time.perf_counter() - start
    if ttft is None:
        return RequestResult(success=False, e2e_ms=e2e * 1000, error="no content received")

    # Prefer the server-reported token count; fall back to counting streamed chunks.
    output_tokens = (usage or {}).get("completion_tokens") or chunks
    return RequestResult(
        success=True,
        ttft_ms=ttft * 1000,
        e2e_ms=e2e * 1000,
        prompt_tokens=(usage or {}).get("prompt_tokens"),
        output_tokens=output_tokens,
    )


async def wait_until_ready(client, base_url: str, model: str, timeout_s: float) -> None:
    """Poll the server with a 1-token request until it answers (model loaded) or time runs out."""
    deadline = time.monotonic() + timeout_s
    last_error = "not attempted"
    while time.monotonic() < deadline:
        result = await stream_chat(client, base_url, model, "Hi", max_tokens=1)
        if result.success:
            return
        last_error = result.error or "unknown"
        await asyncio.sleep(5)
    raise TimeoutError(f"Server at {base_url} not ready after {timeout_s:.0f}s: {last_error}")
