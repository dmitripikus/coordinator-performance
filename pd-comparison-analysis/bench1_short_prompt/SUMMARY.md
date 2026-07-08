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
| **Request latency** mean | 128.0 ms | **116.0 ms** | sidecar, −12.1 ms (−9%) |
| Request latency median | 127.4 ms | **115.8 ms** | sidecar, −11.6 ms (−9%) |
| Request latency p99 | 134.1 ms | **119.3 ms** | sidecar, −14.8 ms (−11%) |
| **TTFT** (time to first token) mean | 33.0 ms | **14.6 ms** | sidecar, −18.3 ms (2.3× faster) |
| TTFT median | 32.3 ms | **14.5 ms** | sidecar, −17.8 ms (2.2× faster) |
| TTFT p99 | 39.1 ms | **17.9 ms** | sidecar, −21.2 ms (2.2× faster) |
| **TPOT** (time per output token) mean | **6.32 ms** | 6.74 ms | coord, −0.42 ms (−6%) |
| Inter-token latency median | **6.74 ms** | 7.20 ms | coord, −0.46 ms (−6%) |
| Norm. time / output token mean | 8.58 ms | **7.78 ms** | sidecar, −0.80 ms (−9%) |
| Output tokens/sec | 15.03 | 15.29 | ~equal (rate-capped) |
| Requests/sec | 1.007 | 1.025 | ~equal (rate-capped) |

### Takeaways
- **Sidecar wins end-to-end** (~116 vs ~128 ms, 9% faster), and the gap is **almost entirely TTFT**: the coordinator adds ~18 ms before the first token (33 vs 15 ms) — the cost of the extra coordinator orchestration hop ahead of prefill.
- **Coordinator streams marginally faster once decoding** (TPOT 6.32 vs 6.74 ms/token, ~6% lower). But with only 15 output tokens, that saving (~0.42 ms × 14 ≈ 6 ms) can't offset the ~18 ms TTFT penalty.
- **Crossover ≈ 43 output tokens:** TTFT favors sidecar by ~18 ms; TPOT favors coord by ~0.42 ms/token. Coordinator only catches up past ~43 output tokens (18.3 / 0.42). For short generations, sidecar is clearly better.

## 2. Coordinator per-step pipeline timing

From `coord/.../llm-d-coordinator-*/coordinator.log`, `pipeline step timings`
(`pipeline/pipeline.go:81`), **n=120** (121 entries, first/warmup entry skipped).
Schema: `parse / prefill / decode`. All values in ms.
(The sidecar setup emits no per-step breakdown — no coordinator.)

| Step | mean | median | min | max | p95 | p99 | share of total |
|------|-----:|-------:|----:|----:|----:|----:|---------------:|
| parse | 0.019 | 0.016 | 0.009 | 0.044 | 0.034 | 0.040 | **0.0%** |
| prefill | 14.861 | 14.580 | 13.500 | 20.513 | 17.238 | 19.069 | **11.7%** |
| decode | 112.252 | 111.724 | 110.629 | 117.200 | 115.757 | 116.826 | **88.3%** |
| **TOTAL** | 127.132 | 126.648 | 124.549 | 134.555 | 131.716 | 133.475 | 100% |

### Takeaways
- **Decode dominates: ~88%** of pipeline time (~112 ms); prefill ~12% (~15 ms); parse negligible (tens of µs).
- Very tight distribution — decode spans only ~7 ms min→max, prefill ~7 ms, no long tail (the warmup first request, prefill 24.9 / decode 122.7 ms, is excluded).
- Pipeline TOTAL (mean 127.3 / median 126.7 ms) matches the benchmark request latency (~128.0 ms) almost exactly → the coordinator pipeline accounts for essentially the whole request; proxy/network overhead is sub-millisecond.

## 3. Where the coordinator loses to the sidecar

The coordinator's TTFT is ~33 ms vs the sidecar's ~15 ms (Δ ≈ 18 ms). Of that:
- **~15 ms is prefill** (unavoidable model work, present in both architectures).
- **~18 ms is coordinator orchestration/routing** *before* prefill starts.

So the sidecar's advantage on short prompts comes from **avoiding that ~18 ms
pre-prefill orchestration hop**, not from faster model execution. For short
outputs where TTFT is the bulk of latency, that hop is the deciding factor;
the coordinator's slightly faster per-token decode only recovers it past
~43 output tokens.
