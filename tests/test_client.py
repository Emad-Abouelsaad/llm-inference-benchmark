import json

import httpx

from llmbench.client import stream_chat


def sse(*events) -> bytes:
    lines = [f"data: {json.dumps(e)}\n\n" for e in events] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


def chunk(text):
    return {"choices": [{"index": 0, "delta": {"content": text}}]}


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_stream_uses_server_usage_when_present():
    body = sse(chunk("Hel"), chunk("lo"), chunk("!"),
               {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 4}})

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/v3/chat/completions"
        assert payload["stream"] is True and payload["max_tokens"] == 16
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    async with make_client(handler) as client:
        r = await stream_chat(client, "http://test/v3", "m", "hi", max_tokens=16)

    assert r.success
    assert r.output_tokens == 4
    assert r.prompt_tokens == 7
    assert r.ttft_ms is not None and r.e2e_ms >= r.ttft_ms


async def test_stream_falls_back_to_chunk_count():
    body = sse(chunk("a"), chunk("b"), chunk(""), chunk("c"))

    async with make_client(lambda req: httpx.Response(200, content=body)) as client:
        r = await stream_chat(client, "http://test/v1", "m", "hi", max_tokens=8)

    assert r.success and r.output_tokens == 3


async def test_http_error_is_reported():
    async with make_client(lambda req: httpx.Response(404, text="model not found")) as client:
        r = await stream_chat(client, "http://test/v1", "m", "hi", max_tokens=8)

    assert not r.success
    assert "404" in r.error and "model not found" in r.error


async def test_ignore_eos_is_sent_only_when_requested():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=sse(chunk("x")))

    async with make_client(handler) as client:
        await stream_chat(client, "http://t/v1", "m", "hi", 4)
        await stream_chat(client, "http://t/v1", "m", "hi", 4, ignore_eos=True)

    assert "ignore_eos" not in seen[0]
    assert seen[1]["ignore_eos"] is True
