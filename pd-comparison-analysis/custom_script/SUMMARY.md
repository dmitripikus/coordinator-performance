# P/D Disaggregation: Coordinator vs Sidecar — Timing Summary

Source: `pd-comparison-analysis/custom_script/`, logs collected 2026-07-07.
**Comparison is reuse-only** (prefix/KV reuse enabled): the coord side has only
the `with-reuse` runs, so the sidecar `no-reuse` runs are excluded for an
apples-to-apples match.

## What is being compared

Two ways of orchestrating prefill/decode (P/D) disaggregation, driven by the
same `reqsend` load generator (10 requests per run):

| Setup | Dir | Namespace | Orchestration | Pods |
|-------|-----|-----------|---------------|------|
| **Coordinator** | `pd-coord-logs/` | `dpikus-epd` | dedicated `llm-d-coordinator` pod runs the pipeline | 10 |
| **Sidecar** | `pd-sidecar-logs/` | `dpikus-pd` | `routing-proxy` sidecar next to the decode modelserver; no coordinator pod | 6 |

Each was run with `short` and `long` prompts. Top-level `*-times-*.txt` files
are the gateway (istio) end-to-end durations; the coordinator's per-step
breakdown is in `.../llm-d-coordinator-*/coordinator.log` (`pipeline step
timings`, `pipeline/pipeline.go:81`). The sidecar setup emits no per-step
pipeline breakdown — it has no coordinator.

## Gateway end-to-end latency (ms, reuse only, n=10)

| Scenario | min | mean | median | sd | max |
|----------|----:|-----:|-------:|----:|----:|
| coord   short | 134.37 | 138.30 | **136.15** | 4.90 | 149.88 |
| sidecar short | 121.28 | 122.70 | **121.41** | 3.32 | 132.02 |
| coord   long  | 71.10 | 1621.28 | **1791.75** | 544.70 | 1805.92 |
| sidecar long  | 1880.52 | 1882.53 | **1880.78** | 3.05 | 1888.80 |

### Head-to-head (median)

| Prompt | coord | sidecar | winner | gap |
|--------|------:|--------:|--------|-----|
| short  | 136.15 | 121.41 | **sidecar** | ~15 ms (sidecar ~11% faster) |
| long   | 1791.75 | 1880.78 | **coordinator** | ~89 ms (coord ~5% faster) |

Use the **median** for coord-long: one request hit KV reuse and returned in
71 ms (its decode was 30.8 ms vs ~1.75 s for the rest), pulling the mean down
to 1621 ms while the median stays at ~1792 ms. That single hit is the only
observed instance of prefix reuse firing across the runs.

## Coordinator pipeline steps (reuse run, ms, n=10)

Schema: `parse / prefill / decode` (prefill and decode broken out per request).

| Prompt | parse | prefill (mean / med / max) | decode (mean / med / max) |
|--------|------:|---------------------------:|--------------------------:|
| short  | ~0.02 | 15.96 / 15.36 / 21.55 | 121.61 / 120.16 / 127.11 |
| long   | ~0.10 | 37.58 / 36.99 / 45.33 | 1582.56 / 1754.42 / 1757.72 |

- **Decode is ~99% of the pipeline.** Prefill is ~16 ms (short) / ~37 ms (long); parse is negligible (tens of µs).
- The gateway end-to-end (~136 ms short / ~1792 ms long) ≈ prefill + decode + a few ms of proxy overhead — the pipeline *is* the latency, and model decode dominates it.

## Bottom line

- **Short prompts → sidecar wins** (~121 vs ~136 ms). When model work is small, the coordinator's extra hop adds ~15 ms that matters.
- **Long prompts → coordinator wins** (~1792 vs ~1881 ms, ~5%). Once decode dominates (~1.75 s), the coordinator's path is slightly leaner.
- The ranking is **prompt-size dependent**, not a clean win either way. Coordinator runs more pods (10 vs 6) for the long-prompt edge.
- Prefix/KV reuse fired only once across all runs (the coord-long 71 ms request), so it is not a reliable latency lever for this workload — requests are decode-bound.
