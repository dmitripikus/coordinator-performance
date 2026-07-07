# bench1 — Short Prompt: Coordinator vs Sidecar

Benchmark: `inference-perf`, model `openai/gpt-oss-120b`, P/D disaggregation.
Load: constant **1 req/s for 120 s → 120 requests**, streaming completion,
input = 1 token, output = 15 tokens. **0 failures** in both runs. Configs are
identical between `coord/` and `sidecar/`, so this is a clean apples-to-apples
latency comparison (not a saturation test — throughput is rate-capped).

- **Coordinator** (`coord/`, ns `dpikus-epd`): dedicated `llm-d-coordinator` pod orchestrates the pipeline.
- **Sidecar** (`sidecar/`, ns `dpikus-pd`): `routing-proxy` sidecar next to the decode server; no coordinator pod.

## 1. End-to-end comparison (n=120, 0 failures)

| Metric | Coordinator | Sidecar | Winner |
|--------|------------:|--------:|--------|
| **Request latency** mean | 131.9 ms | **116.0 ms** | sidecar, −15.9 ms (−12%) |
| Request latency median | 131.5 ms | **115.8 ms** | sidecar, −15.7 ms |
| Request latency p99 | 139.6 ms | **119.3 ms** | sidecar, −20.3 ms |
| **TTFT** (time to first token) mean | 37.3 ms | **14.6 ms** | sidecar, −22.7 ms (2.6× faster) |
| TTFT median | 36.9 ms | **14.5 ms** | sidecar |
| TTFT p99 | 44.8 ms | **17.9 ms** | sidecar |
| **TPOT** (time per output token) mean | **6.29 ms** | 6.74 ms | coord, −0.45 ms (−7%) |
| Inter-token latency median | **6.71 ms** | 7.20 ms | coord |
| Norm. time / output token mean | 8.84 ms | **7.78 ms** | sidecar |
| Output tokens/sec | 15.00 | 15.28 | ~equal (rate-capped) |
| Requests/sec | 1.005 | 1.025 | ~equal (rate-capped) |

### Takeaways
- **Sidecar wins end-to-end** (~116 vs ~132 ms, 12% faster), and the gap is **almost entirely TTFT**: the coordinator adds ~23 ms before the first token (37 vs 15 ms) — the cost of the extra coordinator orchestration hop ahead of prefill.
- **Coordinator streams marginally faster once decoding** (TPOT 6.29 vs 6.74 ms/token, ~7% lower). But with only 15 output tokens, that saving (~0.45 ms × 14 ≈ 6 ms) can't offset the ~23 ms TTFT penalty.
- **Crossover ≈ 50 output tokens:** TTFT favors sidecar by ~23 ms; TPOT favors coord by ~0.45 ms/token. Coordinator only catches up past ~50 output tokens. For short generations, sidecar is clearly better.

## 2. Coordinator per-step pipeline timing

From `coord/.../llm-d-coordinator-*/coordinator.log`, `pipeline step timings`
(`pipeline/pipeline.go:81`), **n=121**. Schema: `parse / prefill / decode`.
All values in ms. (The sidecar setup emits no per-step breakdown — no coordinator.)

| Step | mean | median | min | max | p95 | p99 | share of total |
|------|-----:|-------:|----:|----:|----:|----:|---------------:|
| parse | 0.022 | 0.024 | 0.007 | 0.046 | 0.033 | 0.042 | **0.0%** |
| prefill | 16.611 | 15.901 | 14.282 | 28.757 | 20.188 | 21.997 | **12.7%** |
| decode | 114.586 | 114.104 | 111.804 | 124.883 | 117.716 | 121.337 | **87.3%** |
| **TOTAL** | 131.218 | 130.644 | 126.374 | 153.663 | 136.993 | 143.360 | 100% |

### Takeaways
- **Decode dominates: ~87%** of pipeline time (~115 ms); prefill ~13% (~17 ms); parse negligible (tens of µs).
- Very tight distribution — decode spans only ~13 ms min→max, prefill ~14 ms, almost no long tail (the 153.7 ms max is a single outlier).
- Pipeline TOTAL (mean 131.2 / median 130.6 ms) matches the benchmark request latency (~131.9 ms) almost exactly → the coordinator pipeline accounts for essentially the whole request; proxy/network overhead is sub-millisecond.

## 3. Where the coordinator loses to the sidecar

The coordinator's TTFT is ~37 ms vs the sidecar's ~15 ms (Δ ≈ 22 ms). Of that:
- **~17 ms is prefill** (unavoidable model work, present in both architectures).
- **~20 ms is coordinator orchestration/routing** *before* prefill starts.

So the sidecar's advantage on short prompts comes from **avoiding that ~20 ms
pre-prefill orchestration hop**, not from faster model execution. For short
outputs where TTFT is the bulk of latency, that hop is the deciding factor.
