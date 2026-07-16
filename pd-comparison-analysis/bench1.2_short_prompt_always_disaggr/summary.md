# bench1.2_short_prompt_always_disaggr — coord vs sidecar

Workload: 120 requests, `random_1_15_isl_osl` (1 input token / 15 output tokens),
constant rate 1 req/s, model `openai/gpt-oss-120b`, streaming. Same workload as
the earlier short-prompt benches, but this time the sidecar's EPP was
reconfigured to always disaggregate: `prefix-based-pd-decider`'s
`nonCachedTokens` parameter set to `0` (was `300`), so every request gets a
real prefill-node round trip regardless of prompt size.

Data sources: each run's own `summary_lifecycle_metrics.json` (official,
n=120), coord's `coordinator.log` (per-request `parse`/`prefill`/`decode`
pipeline timings), and sidecar's `routing-proxy.log` (per-request
`sidecar received request` → `forwarding request to prefill node` →
`received prefill response, sending decode request` → `receiving decode
response`). Both logs are filtered to the last 120 real requests by
timestamp, dropping the pre-run smoke-test request and one early retry.

## Official numbers (n=120)

| metric | coord | sidecar | diff (coord − sidecar) | % diff (vs sidecar) |
|---|---|---|---|---|
| request latency (mean) | 138.55 ms | 134.71 ms | +3.84 ms | +2.85% |
| request latency (median) | 138.57 ms | 134.92 ms | +3.65 ms | +2.71% |
| TTFT (mean) | 35.14 ms | 32.46 ms | +2.68 ms | +8.26% |
| TTFT (median) | 35.32 ms | 32.54 ms | +2.78 ms | +8.54% |
| time per output token (mean) | 6.874 ms | 6.799 ms | +0.075 ms | +1.10% |

With both architectures always disaggregating, coordinator and sidecar land
within **~3-4ms of each other** on total latency — a small, single-digit
gap, not the ~20ms gap seen when the sidecar's EPP was allowed to skip
disaggregation for this same short-prompt workload.

## Internal breakdown, from each architecture's own instrumentation

**coord** (`coordinator.log`, last 120 real requests):

| stage | mean | median |
|---|---|---|
| parse | 0.026 ms | 0.028 ms |
| prefill leg | 15.85 ms | 15.75 ms |
| decode leg | 121.63 ms | 121.44 ms |
| **total** | **137.50 ms** | 137.44 ms |

**sidecar** (`routing-proxy.log`, last 120 real requests):

| stage | mean | median |
|---|---|---|
| dispatch (routing decision) | 0.073 ms | 0.069 ms |
| prefill leg (forward → full prefill response) | 14.62 ms | 14.29 ms |
| request → first decode byte | 18.37 ms | 18.04 ms |

`coordinator.log`'s `total` reconciles closely with the official
request-latency mean (137.50 vs 138.55, coord). Sidecar's routing-proxy
log doesn't carry a full-completion timestamp (its last message fires on
the first bytes of the decode response, not stream completion), so its
`total` isn't directly comparable to `coordinator.log`'s — the official
`summary_lifecycle_metrics.json` numbers are the reliable total-latency
source for both sides; the routing-proxy breakdown is only used here for
the prefill-leg and dispatch components.

## Reading it

- **Prefill leg is now nearly identical**: coord 15.85ms vs sidecar
  14.62ms — both architectures pay a real cross-pod prefill round trip on
  every request, within ~1ms of each other.
- **Decode-per-token cost is essentially the same** (6.874ms vs 6.799ms,
  <0.08ms apart) — neither architecture is faster at the actual GPU work.
- The residual ~3-4ms gap in total latency is small enough to plausibly be
  normal run-to-run variance (different pods/nodes, single-run capture)
  rather than a structural cost of one architecture over the other — unlike
  the ~20ms gap measured when the sidecar's EPP was skipping
  disaggregation for this same workload.

**Bottom line**: once both architectures are configured to do the same
work (always split prefill and decode), coordinator and sidecar perform
within a few milliseconds of each other on this short-prompt workload. The
large gap seen in earlier short-prompt benches was not an inherent
coordinator-vs-sidecar architectural cost — it was the sidecar's EPP
quietly skipping the prefill hop for small prompts while the coordinator
always paid it.
