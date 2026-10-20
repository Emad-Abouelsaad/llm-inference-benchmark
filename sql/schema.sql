-- One row per benchmark invocation (e.g. one GitHub Actions job).
CREATE TABLE IF NOT EXISTS benchmark_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_uuid        UUID        NOT NULL UNIQUE,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    backend         TEXT        NOT NULL,          -- openvino | vllm | other
    model           TEXT        NOT NULL,
    base_url        TEXT        NOT NULL,
    max_tokens      INTEGER     NOT NULL,
    git_sha         TEXT,
    git_ref         TEXT,
    ci_run_id       TEXT,
    hardware        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    notes           TEXT
);

-- Aggregated metrics for one concurrency level within a run.
CREATE TABLE IF NOT EXISTS benchmark_results (
    id                      BIGSERIAL PRIMARY KEY,
    run_id                  BIGINT  NOT NULL REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    concurrency             INTEGER NOT NULL,
    num_requests            INTEGER NOT NULL,
    num_failed              INTEGER NOT NULL,
    duration_s              DOUBLE PRECISION NOT NULL,
    request_throughput      DOUBLE PRECISION,           -- requests / s
    output_token_throughput DOUBLE PRECISION,           -- generated tokens / s (all requests)
    total_output_tokens     INTEGER,
    ttft_mean_ms            DOUBLE PRECISION,
    ttft_p50_ms             DOUBLE PRECISION,
    ttft_p90_ms             DOUBLE PRECISION,
    ttft_p99_ms             DOUBLE PRECISION,
    tpot_mean_ms            DOUBLE PRECISION,
    tpot_p50_ms             DOUBLE PRECISION,
    tpot_p99_ms             DOUBLE PRECISION,
    e2e_mean_ms             DOUBLE PRECISION,
    e2e_p50_ms              DOUBLE PRECISION,
    e2e_p99_ms              DOUBLE PRECISION,
    UNIQUE (run_id, concurrency)
);

-- Raw per-request measurements, kept for later re-analysis.
CREATE TABLE IF NOT EXISTS request_metrics (
    id              BIGSERIAL PRIMARY KEY,
    result_id       BIGINT  NOT NULL REFERENCES benchmark_results(id) ON DELETE CASCADE,
    success         BOOLEAN NOT NULL,
    ttft_ms         DOUBLE PRECISION,
    tpot_ms         DOUBLE PRECISION,
    e2e_ms          DOUBLE PRECISION,
    prompt_tokens   INTEGER,
    output_tokens   INTEGER,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_model_started ON benchmark_runs (model, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_request_metrics_result ON request_metrics (result_id);

-- Convenience view: one flat row per (run, concurrency) for dashboards / BI tools.
CREATE OR REPLACE VIEW v_benchmark_summary AS
SELECT r.run_uuid, r.started_at, r.backend, r.model, r.git_sha,
       r.hardware ->> 'cpu_model' AS cpu_model,
       b.concurrency, b.num_requests, b.num_failed,
       b.request_throughput, b.output_token_throughput,
       b.ttft_p50_ms, b.ttft_p99_ms, b.tpot_p50_ms, b.e2e_p50_ms
FROM benchmark_runs r
JOIN benchmark_results b ON b.run_id = r.id;
