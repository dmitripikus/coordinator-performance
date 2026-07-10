# bench5 — 5000 in / 250 out under load (2D/8P): Coordinator vs Sidecar

Benchmark: `inference-perf`, model `openai/gpt-oss-120b`, P/D disaggregation.
Prompt shape: **5000 input → 250 output tokens**, streaming completion.
Load: **constant 45 req/s for 120 s → 5400 requests** (`num_workers: 45`,
`worker_max_concurrency: 100`). **0 failures** in both runs. Topology **2 decode +
8 prefill** pods. Configs are identical between `coord/` (ns `dpikus-epd`) and
`sidecar/` (ns `dpikus-pd`) — clean apples-to-apples.

> **This is bench2's workload shape (5000/250) at ~170× the load.** bench2 ran
> the same prompt shape at **0.25 req/s** (never queued → a tie). bench5 drives
> **45 req/s**, deep into saturation — so this measures behavior **under
> contention**, where queueing, not single-stream latency, decides the winner.

- **Coordinator**: dedicated `llm-d-coordinator` pod orchestrates the pipeline.
- **Sidecar**: `routing-proxy` sidecar next to the decode server; no coordinator pod.

## 1. End-to-end comparison (n=5400, 0 failures)

| Metric | Coordinator | Sidecar | Winner |
|--------|------------:|--------:|--------|
| **Request latency** mean | 5715.9 ms | **5478.1 ms** | sidecar, −237.8 ms (−4.2%) |
| Request latency median | 5181.3 ms | **5104.5 ms** | sidecar, −76.8 ms (−1.5%) |
| Request latency p90 | 8211.2 ms | **7526.8 ms** | sidecar, −684.3 ms (−8.3%) |
| Request latency p99 | 12 740.9 ms | **10 660.2 ms** | sidecar, −2080.7 ms (−16.3%) |
| **TTFT** (time to first token) mean | 2390.0 ms | **2134.7 ms** | sidecar, −255.3 ms (−10.7%) |
| TTFT median | 1842.9 ms | **1744.4 ms** | sidecar, −98.5 ms (−5.3%) |
| TTFT p99 | 9234.0 ms | **7215.5 ms** | sidecar, −2018.5 ms (−21.9%) |
| **TPOT** (time per output token) mean | **13.258 ms** | 13.318 ms | coord, −0.06 ms (−0.5%) — tie |
| TPOT median | 13.458 ms | **13.451 ms** | ~equal |
| Inter-token latency mean | **13.257 ms** | 13.318 ms | coord, −0.06 ms — tie |
| Norm. time / output token mean | 23.224 ms | **22.241 ms** | sidecar, −0.98 ms (−4.4%) |
| Requests/sec (delivered) | 42.47 | **43.41** | sidecar, +0.94 (+2.2%) |
| Input tokens/sec | 218 794 | **223 608** | sidecar, +2.2% |
| Output length (median / mean) | 246 / 283.8 | 246 / 284.7 | ~equal (see caveat) |

### Takeaways
- **Sidecar wins under load**, and the win is concentrated in **TTFT and the tail**, not steady-state streaming: TTFT p99 is **21.9% lower**, request-latency p99 **16.3% lower**. Medians are close (~1.5%); the gap opens up as you climb the percentiles.
- **TPOT / inter-token latency is a dead tie** (~13.3 ms/token both). Once a request is decoding, both architectures stream at the same rate — the difference is entirely in **getting to the first token**.
- **Mechanism:** at 45 req/s the coordinator's separate, serialized **prefill leg** (cross-pod hop + KV-cache transfer before decode can start) queues under contention. The coordinator log shows prefill-leg time with a **p99 of ~9.1 s** (mean 2.2 s, median 1.7 s) — a large queuing tail that inflates TTFT. The sidecar collapses that hop by sitting next to the decode server, so its TTFT tail stays tighter.
- **Contrast with bench2 (tie at 0.25 req/s):** the coordinator's pre-decode hop is a rounding error when nothing queues. Add saturation and that same hop becomes the tail-latency differentiator. Same shape, opposite conclusion — **load is the deciding variable**.

> ⚠️ **Output length — same client-side counting artifact as bench2.**
> Both runs report `output_len` median **246** (≈ the 250 target) but mean ~**284**
> with a **max of ~5432**. This is the known `inference-perf` token-counting
> artifact (a handful of requests mis-counted), **not** over-generation — it hits
> both runs equally, so `output_tokens_per_sec` is polluted the same way on both
> sides. `requests_per_sec` and all latency metrics are trustworthy.

## 2. Coordinator per-step pipeline timing

From `coord/pod_logs_dpikus-epd_20260709_174611/llm-d-coordinator-84d7dc5ff8-dcmmz/coordinator.log`,
`pipeline step timings` (`pipeline/pipeline.go:81`). Schema: `parse / prefill /
decode`, values in ms. (The sidecar emits no per-step breakdown — no coordinator.)

> The log holds **5853** entries; the run sent **5400**. The extra ~453 are the
> **10 s warmup** (45 req/s × 10 s) logged first. Those cold entries are dropped —
> the table below is the **last 5400 entries** (the main run). With warmup removed,
> pipeline-TOTAL mean (5701 ms) matches the client-measured request latency
> (5716 ms) to within ~15 ms.

| Step | mean | median | min | max | p95 | p99 | share |
|------|-----:|-------:|----:|----:|----:|----:|------:|
| parse | 0.359 | 0.347 | 0.314 | 5.423 | 0.416 | 0.498 | **0.01%** |
| prefill | 2240.2 | 1688.4 | 157.5 | 11 962.0 | 6210.9 | 9070.5 | **39.3%** |
| decode | 3460.8 | 3505.2 | 2058.3 | 3901.3 | 3732.4 | 3819.8 | **60.7%** |
| **TOTAL** | 5701.3 | 5166.9 | 2270.7 | 15 546.0 | 9703.8 | 12 727.1 | 100% |

### Takeaways
- **Orchestration is not the cost.** `parse` (the coordinator's own request handling) is **~0.36 ms**, 0.01% of the pipeline. The coordinator's non-model overhead is negligible, consistent with the bench4 gateway trace (~0.1–1 ms).
- **Prefill is where load bites.** Prefill median is 1.69 s but its **p99 is ~9.1 s** (max ~12 s) — a large queuing tail under 45 req/s across 8 prefill pods. Decode is far tighter (median 3.51 s, p99 3.82 s). The prefill-leg tail is exactly what drives the coordinator's TTFT-p99 disadvantage in §1.
- **Decode ≈ 61%, prefill ≈ 39%** of pipeline time on average — but the *variance* lives almost entirely in prefill (decode min→max spans ~1.8 s; prefill spans ~11.8 s).

## 3. Bottom line

At **45 req/s** on a 5000/250 workload, the **sidecar is faster** — ~4% on mean
latency, but **16–22% on p99 latency and TTFT**. Steady-state streaming (TPOT) is
identical; the entire advantage is a **tighter TTFT tail**, because the sidecar
avoids the coordinator's separate prefill-leg hop that queues under contention
(coordinator prefill p99 ~9 s).

Combined with the earlier benchmarks, the picture is now load-aware:

| Workload | Load | Bottleneck | Winner | Why |
|----------|------|-----------|--------|-----|
| bench1 short (1/15) | 1 req/s | TTFT | **sidecar** (~9%) | avoids pre-prefill orchestration hop |
| bench2 long (5000/250) | 0.25 req/s | balanced, unloaded | **tie** | nothing queues; hop is noise |
| bench3 decode-heavy (250/5000) | serial | decode/TPOT | **coordinator** (~7%) | faster per-token streaming dominates |
| **bench5 long under load (5000/250)** | **45 req/s** | **TTFT tail / prefill queue** | **sidecar** (~16–22% p99) | prefill-leg hop queues under saturation |

**Rule of thumb:** the coordinator's extra prefill-leg hop is free when idle and
under decode-bound workloads, but becomes a tail-latency liability once prefill
queues. Choose **sidecar for latency-SLO / TTFT-sensitive traffic at high load**;
**coordinator for decode-bound or low-contention workloads**.
