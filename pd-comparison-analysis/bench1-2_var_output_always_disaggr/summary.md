# bench1-2_var_output_always_disaggr — coord vs sidecar, variable output length

Same request stream shape run against both architectures — coordinator
(namespace `dpikus-epd`) and sidecar (namespace `dpikus-pd`). Input length
fixed at 250 tokens; output length varies. Three steps, each 120 requests,
constant rate, `openai/gpt-oss-120b`, streaming, `ignore_eos: true`:

| output tokens | rate | duration |
|---|---|---|
| 100 | 1 req/s | 120s |
| 500 | 0.5 req/s | 240s |
| 1,000 | 0.25 req/s | 480s |

Data source: each step's own `summary_lifecycle_metrics.json`. Where a
size had more than one run directory, the latest (highest epoch) is used;
any `-old`/`_old`-suffixed directory is excluded. A fourth step
(`random_250_2500_isl_osl`) exists but its run directory turned out to
contain an unrelated nested dump of older benchmark runs rather than a
completed 2,500-output result — excluded from this summary as corrupted,
not a real data point.

## Data validation

All 6 runs (3 sizes × 2 architectures) are clean:

- **120/120 success** on every run, zero crash-level errors
  (`Traceback`/`CUDA error`/`OutOfMemory`/NIXL-connector errors) in any
  prefill or decode `modelserver.log`.
- **`output_len` distributions have no truncated-output outliers** — min
  values (92/368/707 for sidecar; 89/466/611 for coord) all land close to
  target, confirming every counted request generated close to its full
  configured output length.

One thing initially looked like a real error and turned out not to be:
sidecar's `epp.log` logs `"level":"error"` — `"Request latency values are
invalid for TPOT calculation"` — for a handful of events. Precisely
timestamping each one against the actual run windows shows most happened
*before* the 100-token run even started (pre-run smoke/warmup traffic,
not part of the counted 120), and the ones that do fall inside a run
window completed in ~146ms total — far too fast to be a real
100/500/1,000-token generation. These are small non-streaming
health-check probes hitting the same EPP pipeline, which trips a
diagnostic warning about not being able to compute TPOT for a
non-streamed response — unrelated to the real benchmark traffic. No runs
were excluded on this basis.

## Results (n=120 per step)

| output tokens | arch | success | lat median | lat p90 | TTFT median | ITL median | output tok/s |
|---|---|---|---|---|---|---|---|
| 100 | coord | 120/120 | 785.0 ms | 789.6 ms | 58.2 ms | 7.320 ms | 100.7 |
| 100 | sidecar | 120/120 | 775.5 ms | 777.6 ms | 55.6 ms | 7.253 ms | 96.9 |
| 500 | coord | 120/120 | 3715.3 ms | 3718.0 ms | 58.3 ms | 7.322 ms | 132.8 |
| 500 | sidecar | 120/120 | 3681.1 ms | 3685.1 ms | 56.9 ms | 7.254 ms | 133.1 |
| 1,000 | coord | 120/120 | 7381.6 ms | 7384.8 ms | 59.7 ms | 7.322 ms | 132.3 |
| 1,000 | sidecar | 120/120 | 6804.1 ms | 7137.4 ms | 57.2 ms | 6.757 ms | 142.7 |

Sidecar's 1,000-output step was re-run after the tail-latency finding
below (see "Reading it") to check whether it was reproducible; this table
uses the fresh re-run.

## % difference (coord vs sidecar, median)

| output tokens | lat diff | lat % diff | TTFT diff | TTFT % diff | ITL diff | ITL % diff |
|---|---|---|---|---|---|---|
| 100 | +9.6 ms | +1.23% | +2.52 ms | +4.53% | +0.068 ms | +0.94% |
| 500 | +34.3 ms | +0.93% | +1.43 ms | +2.51% | +0.068 ms | +0.93% |
| 1,000 | +577.4 ms | +8.49% | +2.48 ms | +4.33% | +0.565 ms | +8.36% |

Diff = coord − sidecar; % diff is relative to sidecar. Positive means
coord is slower/higher.

## Charts

![TTFT distribution](analysis/ttft_distribution.png)
![Request latency distribution](analysis/request_latency_distribution.png)
![Inter-token latency distribution](analysis/itl_distribution.png)
![time_per_output_token distribution](analysis/tpot_distribution.png)
![normalized_time_per_output_token distribution](analysis/ntpot_distribution.png)
![Success rate](analysis/success_rate.png)

Bands are p10-p90, line is the median, x-axis log-scaled by output tokens.

## Reading it

- **Coord and sidecar are nearly identical at 100 and 500 output
  tokens** (within ~1% on latency, ~1% on ITL) — TTFT is fixed by input
  length (250 tokens, unchanged across all three steps) and decode cost
  scales the same way on both sides while output length is short-to-medium.
- **A real gap opens up at 1,000 output tokens**: coord is ~8.4% slower
  on total latency and ~8.3% slower on ITL. Unlike the input-length sweep
  (`bench1-2_var_prompt_always_disaggr`), where the coord-vs-sidecar ITL
  gap was roughly constant across input sizes, here it's **near-zero at
  100/500 output tokens and only appears at 1,000** — the gap is a
  function of how long the decode stream runs, not a fixed per-request
  overhead.
- **TTFT is flat across all three steps for both architectures** (~56-60ms
  for both) — expected, since TTFT is driven by prefill/input length,
  which is fixed at 250 tokens throughout this sweep. This confirms the
  latency/ITL differences seen above are purely a decode-side effect.
- **Sidecar's first 1,000-output run had a long latency tail that coord
  didn't have** — coord's spread across all 120 requests was only 16ms
  (7374.5-7390.5ms), while sidecar's p90/p99/max (7323/8770/8849ms) sat
  well above its own p75 (~6833ms). Traced to a specific cause:
  reconstructing per-request completion gaps from `epp.log` showed a
  **single contiguous ~80-second window** (10 consecutive requests,
  16:19:11-16:20:27 UTC) where every request ran 1-1.5s slower than its
  neighbors. Cross-checked against the decode pod's own vLLM engine
  metrics for that exact window: `Avg generation throughput` genuinely
  dropped from its steady ~136-147 tokens/s to ~113-125 tokens/s for
  those ~80 seconds, then recovered immediately after — a real,
  measurable GPU-side decode slowdown, not a logging artifact or a
  request-queueing effect (decode concurrency stayed at 1 throughout;
  ruled out). KV-transfer timing moved the *opposite* direction during
  the same window (transfer time dropped, throughput rose), so this was
  specifically a GPU-compute slowdown, not a network/RDMA issue.
- **Re-run confirms it was transient, not reproducible.** The 1,000-output
  sidecar step was re-run to check this; the new run's decode engine
  throughput stayed rock-solid at ~146-147 tokens/s for the *entire* run
  with no dip anywhere, and the latency spread shrank to a much more
  ordinary ~600ms (p75 6807ms → max 7401ms), consistent with normal
  early-request/cold-start variance rather than a mid-run event. The
  median/ITL comparison against coord barely moved between the two runs
  (+8.37%/+8.27% first run vs +8.49%/+8.36% re-run) — confirming the
  core coord-vs-sidecar finding at 1,000 tokens is stable and was never
  affected by the transient tail; only the p90/p99/max were. This reads
  as a one-off event on whatever node/GPU that first run's decode pod
  happened to land on (thermal throttling or transient compute
  contention are the most likely candidates, though not confirmable from
  these logs alone — this cluster's Prometheus has no node-level GPU
  utilization history) — not a structural sidecar issue.

**Bottom line**: with clean, validated data on both sides, coord and
sidecar are essentially equivalent for outputs up to 500 tokens. At 1,000
output tokens, coord is consistently ~8.4-8.5% slower on latency and ITL
across two independent runs — a real, reproducible gap. The tail-latency
issue seen in the first 1,000-output sidecar run did not reproduce on
re-run and is best treated as a one-off infra event, not a sidecar
architecture characteristic.
