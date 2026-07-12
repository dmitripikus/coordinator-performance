# bench6 — 250-in / 4000-out, 3D/8P: Coordinator vs Sidecar (tuned coordinator)

Benchmark: `inference-perf`, model `openai/gpt-oss-120b`, P/D disaggregation,
**3 decode + 8 prefill** pods (3D/8P) in both arms.
Load: target **10 req/s**, gaussian **ISL ≈ 257 / OSL ≈ 3910 tokens** (nominal
250-in / 4000-out), streaming, **1200 requests**, **0 failures** in both runs.
Configs identical between `coord/` and `sidecar/` → apples-to-apples.

- **Coordinator** (`coord/`, ns `dpikus-epd`, collection `…_154534`): **3 coordinator replicas**, tuned resources (see §3).
- **Sidecar** (`sidecar/`, ns `dpikus-pd`): `routing-proxy` sidecar next to each decode server; no coordinator pod.


## 1. End-to-end comparison (n=1200, 0 failures)

| Metric | Coordinator | Sidecar | Δ |
|--------|------------:|--------:|---|
| **Request latency** mean | 63.21 s | **62.92 s** | coord +0.29 s (+0.5%) |
| Request latency median | 64.94 s | **64.51 s** | +0.43 s |
| Request latency p90 | 68.61 s | **67.98 s** | +0.63 s |
| Request latency p99 | 69.22 s | **68.16 s** | +1.06 s |
| **TTFT** mean | 0.143 s | **0.137 s** | coord +6.2 ms (+4.5%) |
| TTFT median | 0.144 s | **0.139 s** | +4.3 ms |
| TTFT p90 | 0.172 s | **0.163 s** | +9.5 ms |
| TTFT p99 | 0.206 s | **0.189 s** | +16.7 ms |
| TTFT max | 0.336 s | **0.220 s** | +116 ms |
| **TPOT** mean | 15.76 ms | **15.69 ms** | ~tie |
| TPOT p99 | 17.27 ms | **17.00 ms** | ~tie |
| Norm. time / output token mean | 16.17 ms | **16.12 ms** | ~tie |
| Output tokens/sec | 26 373 | **26 515** | sidecar +0.5% |
| Requests/sec (achieved) | 6.74 | 6.79 | (target 10) |

### Takeaways
- **The two architectures are performance-equivalent here.** Coordinator is ~0.5% slower end-to-end and carries only a **~6–17 ms TTFT gap** across percentiles — back to the fixed-cost orchestration overhead first measured in the light bench1 run (~18 ms), i.e. the coordinator's inherent extra gateway/EPP hop before prefill.
- **The seconds-scale TTFT tail is gone.** TTFT stays sub-second at every percentile (p99 0.21 s, max 0.34 s), versus the 5000-out run where the coordinator hit p90 5.4 s / p99 7.9 s.
- **TPOT and throughput are effectively identical** (~15.7 ms/token, ~26.4k tok/s). Decode is not saturated in this run (TPOT ~16 ms vs ~31 ms in the 5000-out saturation run).

## 2. Coordinator health (this run)
- **0 request failures**, all 3 coordinator replicas `Restart Count: 0`, no OOM.
- **Load evenly balanced across replicas: 400 / 400 / 401 completions.**
- Decode-server peak concurrency `Running: 241`.

## 3. Bottom line
With a properly resourced, horizontally-scaled coordinator and a load below the
saturation knee, the coordinator matches the sidecar to within ~0.5% end-to-end
and pays only its inherent ~10 ms extra-hop TTFT tax.
