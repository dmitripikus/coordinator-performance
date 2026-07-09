# bench3 — 250 in / 5000 out (decode-heavy): Coordinator vs Sidecar

Benchmark: `inference-perf`, model `openai/gpt-oss-120b`, P/D disaggregation.
Prompt shape: **250 input tokens → 5000 output tokens** (fixed), streaming
completion. Configured load: 0.25 req/s for 480 s. **0 failures** in both runs,
120 requests each. Configs are **identical** between `coord/` (ns `dpikus-epd`)
and `sidecar/` (ns `dpikus-pd`) — clean apples-to-apples.

> Note on rate: each request takes ~34 s and `worker_max_concurrency: 1`, so the
> load generator runs requests **serially** — effective delivered rate is
> **~0.029 req/s** (1 / 34 s), not the configured 0.25. Both runs are bottlenecked
> identically, so the comparison is still fair; it just measures **single-stream
> latency**, not throughput under concurrency.

- **Coordinator**: dedicated `llm-d-coordinator` pod orchestrates the pipeline.
- **Sidecar**: `routing-proxy` sidecar next to the decode server; no coordinator pod.

## 1. End-to-end comparison (n=120, 0 failures)

| Metric | Coordinator | Sidecar | Winner |
|--------|------------:|--------:|--------|
| **Request latency** mean | **33 944 ms** | 36 475 ms | coord, −2531 ms (−6.9%) |
| Request latency median | **33 943 ms** | 36 473 ms | coord, −2530 ms (−6.9%) |
| Request latency p99 | **33 961 ms** | 36 524 ms | coord, −2563 ms (−7.0%) |
| **TPOT** (time per output token) mean | **6.78 ms** | 7.28 ms | coord, −0.51 ms (−7.0%) |
| Inter-token latency median | **6.77 ms** | 7.28 ms | coord, −0.50 ms (−6.9%) |
| Norm. time / output token mean | **6.95 ms** | 7.46 ms | coord, −0.51 ms (−6.9%) |
| **TTFT** (time to first token) mean | 60.8 ms | **58.7 ms** | sidecar, +2.2 ms (+3.7%) |
| TTFT median | 59.8 ms | **57.9 ms** | sidecar, +1.9 ms (+3.3%) |
| Output tokens/sec | **144.0** | 134.1 | coord, +9.9 (+7.4%) |
| Requests/sec (delivered) | 0.029 | 0.027 | coord, +7.5% |
| Output length (mean / max) | 4888 / 4997 | 4891 / 5209 | ~equal |

### Takeaways
- **Coordinator wins by ~7%** (33.9 s vs 36.5 s), and it's **entirely per-token decode**: TPOT 6.78 vs 7.28 ms/token. Over ~4900 output tokens, that 0.5 ms/token compounds to ~2.5 s — exactly the request-latency gap.
- **TTFT is a tie** (~60 ms both; sidecar marginally lower). With 5000 output tokens, the one first-token cost is noise against the decode phase.
- **This is the mirror image of bench1 (short prompt).** There the sidecar won because TTFT dominated and the coordinator's orchestration hop cost ~20 ms; here the workload is decode-bound, TTFT is irrelevant, and the coordinator's faster per-token streaming wins.
- Output length is clean and equal (~4888 tokens; both runs stopped slightly under the 5000 target).

## 2. Coordinator per-step pipeline timing

From `coord/pod_logs_dpikus-epd_20260709_113749/llm-d-coordinator-84d7dc5ff8-dcmmz/coordinator.log`,
`pipeline step timings` (`pipeline/pipeline.go:81`), `stream:true` requests →
**n=45**. Schema: `parse / prefill / decode`. All values in ms.
(The sidecar setup emits no per-step breakdown — no coordinator.)

> This log captured **45** of the run's requests (46 entries incl. 1 warmup);
> the full harness recorded 120. At ~34 s/request the log window (~25 min) holds
> a representative subset — the distribution is extremely tight, so 45 is ample.

| Step | mean | median | min | max | p95 | p99 | share of total |
|------|-----:|-------:|----:|----:|----:|----:|---------------:|
| parse | 0.052 | 0.052 | 0.042 | 0.066 | 0.063 | 0.066 | **0.0%** |
| prefill | 39.315 | 39.122 | 36.524 | 43.753 | 42.463 | 43.753 | **0.1%** |
| decode | 33 892.868 | 33 893.443 | 33 881.503 | 33 902.315 | 33 901.342 | 33 902.315 | **99.9%** |
| **TOTAL** | 33 932.235 | 33 932.464 | 33 918.823 | 33 945.433 | 33 940.201 | 33 945.433 | 100% |

### Takeaways
- **Decode is essentially the entire request: ~99.9%** (~33.9 s for ~4900 output tokens ≈ 6.9 ms/token). Prefill is ~39 ms (0.1%, 250 input tokens); parse is ~50 µs.
- **Distribution is astonishingly tight** — decode spans only ~21 ms across 45 requests (33 881-33 902 ms) — because at ~0.029 req/s the decode engine serves one request at a time with no contention.
- Pipeline TOTAL (~33 932 ms) matches the benchmark request latency (~33 944 ms) within ~12 ms; the rest is gateway/network + TTFT overhead.

## 3. Bottom line

For a decode-heavy workload (250/5000), the **coordinator is ~7% faster**
end-to-end, driven purely by lower per-token decode latency (TPOT 6.78 vs
7.28 ms). Combined with the benchmarks so far, a clear pattern emerges:

| Workload | Bottleneck | Winner | Why |
|----------|-----------|--------|-----|
| bench1 short (1/15) | TTFT | **sidecar** (~10-15%) | avoids ~20 ms coordinator orchestration hop |
| bench2 long (5000/250) | balanced | **tie** | prefill+decode both matter, effects cancel |
| bench3 decode-heavy (250/5000) | decode/TPOT | **coordinator** (~7%) | faster per-token streaming |

The architecture choice is **workload-dependent**: sidecar for short/interactive
(TTFT-bound) traffic, coordinator for long-generation (decode-bound) traffic.
The ~7% coordinator TPOT edge here is worth confirming — likely lower per-token
overhead in the coordinator's decode streaming path vs the sidecar routing-proxy,
but that mechanism isn't proven from these logs.
