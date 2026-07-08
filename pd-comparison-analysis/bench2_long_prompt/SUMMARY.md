# bench2 — Long Prompt: Coordinator vs Sidecar

Benchmark: `inference-perf`, model `openai/gpt-oss-120b`, P/D disaggregation.
Prompt shape: **5000 input tokens → 250 output tokens** (fixed), streaming
completion. Load: constant **0.25 req/s for 480 s → 120 requests**.
**0 failures** in both runs.

Compares `coord/` (ns `dpikus-epd`) vs `sidecar/` (ns `dpikus-pd`). **Configs are
identical** (same rate, duration, ISL/OSL), so this is a clean apples-to-apples
comparison. `sidecar_previous/` (an earlier 0.5 req/s run) is **excluded** — it
used a different arrival rate and is not comparable.

- **Coordinator**: dedicated `llm-d-coordinator` pod orchestrates the pipeline.
- **Sidecar**: `routing-proxy` sidecar next to the decode server; no coordinator pod.

## 1. End-to-end comparison (n=120, 0 failures)

| Metric | Coordinator | Sidecar | Δ (coord − sidecar) |
|--------|------------:|--------:|--------------------:|
| **Request latency** mean | 1920.7 ms | **1904.6 ms** | +16.1 ms (+0.8%) |
| Request latency median | 1920.0 ms | **1904.0 ms** | +16.0 ms (+0.8%) |
| Request latency p99 | 1935.5 ms | **1920.8 ms** | +14.7 ms (+0.8%) |
| **TTFT** (time to first token) mean | 208.6 ms | **203.2 ms** | +5.4 ms (+2.6%) |
| TTFT median | 208.1 ms | **202.8 ms** | +5.3 ms (+2.6%) |
| TTFT p99 | **218.3 ms** | 220.4 ms | −2.1 ms (−1.0%) |
| **TPOT** (time per output token) mean | 6.80 ms | **6.76 ms** | +0.04 ms (+0.6%) |
| Inter-token latency median | 6.84 ms | **6.79 ms** | +0.05 ms (+0.7%) |
| Norm. time / output token mean | 7.77 ms | **7.76 ms** | +0.01 ms (+0.2%) |
| Requests/sec (delivered) | 0.249 | 0.250 | ~equal |

### Takeaways
- **Statistically a tie.** Every latency metric is within ~1% (TTFT within ~2.6%), well inside run-to-run noise. At matched load, coordinator and sidecar deliver the same long-prompt latency.
- **The short-prompt gap disappears.** In bench1 (short prompt) the sidecar won by ~10-15%, driven by a ~20 ms coordinator orchestration hop in TTFT. Here that hop (~20 ms) is a rounding error against a ~208 ms TTFT (dominated by 5000-token prefill), so it no longer matters.
- **Distributions are tight** for both — at 0.25 req/s (4 s inter-arrival vs ~1.9 s service) neither run queues, so p99 ≈ median.

> ⚠️ **Throughput not compared — client-side token-count artifact (not real over-generation).**
> Coord's harness `output_len` reports mean **330** with a **max of 5410** tokens
> (configured: 250; sidecar is clean at mean 245.6, range 236-254). This is an
> `inference-perf` counting artifact, **not** the model over-generating — proven
> server-side:
> - A 5410-token generation at 6.8 ms/token would take **~37 s**, but the **max**
>   request latency across all 120 requests is **1.95 s**.
> - Every coordinator `decode` step across the 120 benchmark requests is
>   **1740-1751 ms** ≈ 250 tokens; none is longer.
>
> So the model produced ~250 tokens for every request as configured. Only the
> harness's `output_tokens_per_sec` (82.2 vs 61.3) is polluted by the bad count;
> `requests_per_sec` (~0.25, equal) and all latency metrics are trustworthy.

## 2. Coordinator per-step pipeline timing

From `coord/pod_logs_.../llm-d-coordinator-.../coordinator.log`,
`pipeline step timings` (`pipeline/pipeline.go:81`), the **120 `stream:true`
benchmark requests** → **n=120**. Schema: `parse / prefill / decode`. All values
in ms. (The sidecar setup emits no per-step breakdown — no coordinator.)

> The log has 121 entries; the 121st is a `stream:false` warmup probe logged
> ~50 s before the run (a short request: decode 123.6 ms, not 5000/250). It is
> excluded, leaving exactly the 120 requests inference-perf sent.

| Step | mean | median | min | max | p95 | p99 | share of total |
|------|-----:|-------:|----:|----:|----:|----:|---------------:|
| parse | 0.428 | 0.386 | 0.352 | 0.978 | 0.752 | 0.947 | **0.0%** |
| prefill | 162.570 | 162.576 | 157.326 | 174.457 | 165.728 | 167.252 | **8.5%** |
| decode | 1744.357 | 1744.090 | 1740.000 | 1750.947 | 1748.752 | 1750.711 | **91.5%** |
| **TOTAL** | 1907.355 | 1906.987 | 1901.058 | 1925.002 | 1912.593 | 1914.991 | 100% |

### Takeaways
- **Decode dominates: ~92%** of pipeline time (~1744 ms for 250 output tokens ≈ 6.98 ms/token); prefill ~8.5% (~163 ms for 5000 input tokens); parse negligible.
- **Extremely tight** — TOTAL spans only ~24 ms min→max — because at 0.25 req/s the prefill engine is never queued.
- Pipeline TOTAL (~1907 ms) matches the benchmark request latency (~1921 ms) within ~14 ms; the remainder is gateway/network overhead.

## 3. Bottom line

At matched load, **coordinator and sidecar are equivalent for long prompts**
(5000/250): all latency metrics within ~1-3%, a statistical tie. Long-prompt
requests are decode-bound (~92% of the pipeline), so the coordinator's
pre-prefill orchestration hop — which cost it ~10-15% on short prompts — is
negligible here. Architecture choice for long-prompt workloads can therefore be
driven by other factors (pod count, operational simplicity) rather than latency.
Data-quality note: coord's inflated `output_len` (mean 330, max 5410) is an
`inference-perf` token-counting artifact, not real over-generation — server-side
timings confirm every request produced ~250 tokens. Only `output_tokens_per_sec`
is affected; latency and `requests_per_sec` are trustworthy.
