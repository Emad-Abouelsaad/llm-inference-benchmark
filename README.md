# LLM Inference Benchmark

[![CI](https://github.com/Emad-Abouelsaad/llm-inference-benchmark/actions/workflows/ci.yml/badge.svg)](https://github.com/Emad-Abouelsaad/llm-inference-benchmark/actions/workflows/ci.yml)
[![LLM Benchmark](https://github.com/Emad-Abouelsaad/llm-inference-benchmark/actions/workflows/benchmark.yml/badge.svg)](https://github.com/Emad-Abouelsaad/llm-inference-benchmark/actions/workflows/benchmark.yml)

An automated pipeline for benchmarking LLM serving. It runs a large language model inside Docker with
**OpenVINO Model Server** (CPU) or **vLLM** (GPU), measures **time to first token (TTFT)**,
**time per output token (TPOT)** and **throughput** under increasing concurrency, and stores every run in
**PostgreSQL**. **GitHub Actions** runs it on every change and every week, so results build up into a history.

```
┌──────────────── GitHub Actions runner ────────────────┐
│                                                       │
│  ┌──────────────┐  streaming SSE   ┌───────────────┐  │
│  │  llmbench    │ ───────────────▶ │ OVMS / vLLM   │  │
│  │  (asyncio,   │ ◀─────────────── │ Docker, OpenAI│  │
│  │   httpx)     │  tokens + usage  │ compatible API│  │
│  └──────┬───────┘                  └───────────────┘  │
│         │ runs / results / per-request rows           │
│         ▼                                             │
│  ┌──────────────┐     job summary (markdown table),   │
│  │ PostgreSQL   │ ──▶ PNG chart, SQL dump artifacts   │
│  └──────────────┘                                     │
└───────────────────────────────────────────────────────┘
```

## What it measures

| Metric | Definition |
|---|---|
| **TTFT** | Time from sending the request to receiving the first streamed content token (p50 / p90 / p99) |
| **TPOT** | `(end-to-end latency − TTFT) / (output tokens − 1)`, the decode speed one user sees |
| **E2E latency** | Total request time |
| **Output throughput** | Total generated tokens across all concurrent requests ÷ wall-clock time |
| **Request throughput** | Successful requests per second |

The load is closed-loop: at each concurrency level *C*, exactly *C* requests are in flight until
`--num-requests` have finished. Sweeping *C* (for example `1,2,4,8`) shows the latency/throughput trade-off
that continuous batching gives you. Token counts come from the server's `usage` field
(`stream_options.include_usage`). If a server doesn't send it, the tool falls back to counting streamed chunks.

## Example output (GitHub Actions job summary)

| Concurrency | Requests (failed) | Output tok/s | Req/s | TTFT p50 (ms) | TTFT p99 (ms) | TPOT p50 (ms) | E2E p50 (ms) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 16 (0) | … | … | … | … | … | … |

*Run the **LLM Benchmark** workflow once, then paste the real table and the `benchmark.png` chart here.*

## Project layout

```
llmbench/
  client.py    streaming OpenAI-compatible client, TTFT/TPOT timing
  runner.py    concurrency sweep (asyncio semaphore), hardware detection
  metrics.py   percentiles and aggregation
  db.py        PostgreSQL persistence (psycopg 3)
  report.py    markdown report with regression deltas vs. the previous run, matplotlib chart
sql/schema.sql benchmark_runs → benchmark_results → request_metrics, plus a summary view
.github/workflows/
  ci.yml         lint + unit tests + PostgreSQL integration test + Docker build
  benchmark.yml  starts OVMS in Docker, benchmarks it, stores and reports the results
```

## Run it locally

Requirements: Docker and Python 3.10 or newer.

```bash
pip install -r requirements.txt

# CPU: OpenVINO Model Server + PostgreSQL
docker compose --profile openvino up -d
python -m llmbench run --base-url http://localhost:8000/v3 --model tinyllama \
    --backend openvino --concurrency 1,2,4 --num-requests 16 --max-tokens 128
python -m llmbench report --plot results/benchmark.png
```

```bash
# GPU: vLLM (needs an NVIDIA GPU and the NVIDIA Container Toolkit)
docker compose --profile vllm up -d
python -m llmbench run --base-url http://localhost:8000/v1 --model tinyllama --backend vllm \
    --concurrency 1,4,16,32 --num-requests 64 --ignore-eos
```

Both servers use the same client code. The only differences are the URL prefix (`/v3` for OVMS, `/v1` for vLLM)
and the `--backend` label stored with the run.

## GitHub Actions

- **CI** (every push and PR): `ruff`, `pytest` (including a round-trip test against a real PostgreSQL
  service container), and a Docker image build.
- **LLM Benchmark** (push to `main`, weekly cron, or manual run with model, concurrency and token inputs).
  The workflow:
  1. starts PostgreSQL as a service container
  2. starts `openvino/model_server` in Docker, which pulls a pre-quantized INT4 model from Hugging Face
     (cached between runs with `actions/cache`)
  3. waits until the model answers, warms it up, then sweeps the concurrency levels
  4. writes the run to PostgreSQL and posts a markdown table to the job summary
  5. uploads `results.json`, `report.md`, `benchmark.png` and a `pg_dump` of the database as artifacts

GitHub-hosted runners have no GPU, so CI benchmarks the OpenVINO CPU path. The vLLM profile is meant for
local or self-hosted GPU machines.

### Keeping a history across runs

By default each job uses a throwaway PostgreSQL container. To keep a history, and get the 🟢/🔴 regression
deltas against the previous run, add a repository secret named **`DATABASE_URL`** that points to a hosted
PostgreSQL database (for example a free Neon or Supabase database, using `?sslmode=require`).
The workflow uses that secret automatically when it exists.

## Querying the data

```sql
-- Throughput trend for a model at concurrency 4
SELECT started_at, git_sha, output_token_throughput, ttft_p50_ms
FROM v_benchmark_summary
WHERE model = 'llm' AND concurrency = 4
ORDER BY started_at;

-- Tail-latency outliers from raw request data
SELECT r.started_at, m.ttft_ms, m.output_tokens
FROM request_metrics m
JOIN benchmark_results b ON b.id = m.result_id
JOIN benchmark_runs r    ON r.id = b.run_id
WHERE m.success
ORDER BY m.ttft_ms DESC LIMIT 20;
```

## Tech stack

Python (asyncio, httpx, psycopg 3, matplotlib) · Docker / Docker Compose · OpenVINO Model Server ·
vLLM · PostgreSQL · GitHub Actions · pytest / ruff

## License

MIT
