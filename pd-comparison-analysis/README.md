# pd-comparison-analysis — coordinator vs sidecar benchmarks

This directory contains a series of coord-vs-sidecar comparisons on
llm-d's P/D-disaggregated inference stack. Each benchmark tests the same
workload against two architectures deployed in adjacent namespaces on
the same cluster:

- **Coordinator ("epd" guide)** — a dedicated `llm-d-coordinator` (or
  `coordinator-epd-decode-epp` EPP in later benches) sits between the
  gateway and the vLLM pods. Decode pod is picked *after prefill
  completes* ("deferred decode"). Namespaces: `dpikus-epd`,
  `dpikus-epd-sglang-bench`.
- **Sidecar ("pd-disaggregation" guide)** — a `routing-proxy` sidecar
  container runs next to each decode pod; the sidecar EPP picks a
  decode pod *at request arrival* ("early-bind"). Namespaces:
  `dpikus-pd`, `dpikus-pd-sglang-bench`.

Every benchmark folder has this shape:

```
<bench>/
  coord/
    bench_config/     # inference-perf or sglang.bench_serving inputs
    inference-perf_.../ or pod_logs_.../   # results & pod logs
  sidecar/
    bench_config/
    inference-perf_.../ or pod_logs_.../
  SUMMARY.md          # detailed writeup for that bench
  analysis/           # (optional) charts, notebooks, extra analysis
  PLAN.md             # (optional) design rationale
```

Each `SUMMARY.md` is the authoritative source of truth for that bench's
methodology and results; this README is an index and cross-reference.

## Common infrastructure

Two harness families are used:

- **`inference-perf`** (v0.5.2 image `ghcr.io/llm-d/llm-d-benchmark:v0.5.2`) —
  used for the earlier text-only benches (`bench1-*`,
  `1D_1P_250IT_5000OT_decode_heavy`, `2D_8P_5000IT_250OT_prefill_heavy`,
  `3D_8P_250IT_4000OT_decode_heavy`). Driven by
  per-step YAML configs
  (`bench_config/config_*.yaml`). Model: `openai/gpt-oss-120b`.
- **`sglang.bench_serving`** (`lmsysorg/sglang:v0.5.14` in a k8s Job) —
  used for later multimedia/burst benches
  (`3Dx8GPU_3Px8GPU_multimedia_baseline`,
  `3Dx8GPU_3Px8GPU_multimedia_rerun`,
  `3Dx8GPU_3Px8GPU_multimedia_active_request_scorer`, `4Dx2GPU_3Px2GPU_multimedia_burst_baseline`,
  `4Dx2GPU_3Px2GPU_multimedia_burst_constrained`,
  `2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer`, `bench11.1*`,
  `bench11.2*`, `bench13`). Driven by a Job YAML
  (`bench_config/benchmark-job.yaml`). Model: `Qwen/Qwen3-VL-*-Instruct`.

The vLLM image throughout the sglang-driven benches is
`ghcr.io/revit13/vllm-openai:nightly-b50646e5effd7cb5884cd96fdff4c53c18521198.omer4`
(a NIXL-enabled build). All decode pods pass
`--kv-transfer-config '{"kv_connector":"NixlConnector","kv_role":"kv_both"}'`
and `--no-disable-hybrid-kv-cache-manager`. On the sglang side,
`turin-gp` node type is used unless noted otherwise (`kermit_US-EAST-01A`
cluster).

---

## Benchmark index

| Bench | Workload | Model | Fleet | Result |
|---|---|---|---|---|
| [bench1-2_var_output_always_disaggr](bench1-2_var_output_always_disaggr/) | var OT, fixed IT=250 | gpt-oss-120b | 1D/1P | node-hardware artifact; coord ~7-8% slower on decode |
| [bench1-2_var_output_always_disaggr_pinned](bench1-2_var_output_always_disaggr_pinned/) | var OT, fixed IT=250, pods node-pinned | gpt-oss-120b | 1D/1P (pinned) | coord ≈ sidecar within ~1% once nodes match |
| [bench1-2_var_prompt_always_disaggr](bench1-2_var_prompt_always_disaggr/) | var IT, fixed OT=250 | gpt-oss-120b | 1D/1P | coord ~7-8% slower on ITL/latency (later attributed to node variance) |
| [bench1-3_var_prompt_always_disaggr](bench1-3_var_prompt_always_disaggr/) | var IT, fixed OT=20, pods node-pinned | gpt-oss-120b | 1D/1P (pinned) | coord ≈ sidecar; ITL within 0.7% across sizes |
| [1D_1P_250IT_5000OT_decode_heavy](1D_1P_250IT_5000OT_decode_heavy/) | 250 IT / 5000 OT, single-stream | gpt-oss-120b | 1D/1P | coord ~7% faster (decode-bound) |
| [2D_8P_5000IT_250OT_prefill_heavy](2D_8P_5000IT_250OT_prefill_heavy/) | 5000 IT / 250 OT, 45 req/s (saturating) | gpt-oss-120b | 2D/8P | sidecar wins under load (TTFT tail) |
| [3D_8P_250IT_4000OT_decode_heavy](3D_8P_250IT_4000OT_decode_heavy/) | 250 IT / 4000 OT, 10 req/s | gpt-oss-120b | 3D/8P (3 coord replicas) | coord ≈ sidecar within ~0.5% |
| [3Dx8GPU_3Px8GPU_multimedia_baseline](3Dx8GPU_3Px8GPU_multimedia_baseline/) | multimodal, image+text, concurrency 10-40 | Qwen3-VL-235B-A22B | 3D×8GPU / 3P×8GPU | sidecar ~2-2.3× faster (coord prefill pool bottleneck) |
| [3Dx8GPU_3Px8GPU_multimedia_rerun](3Dx8GPU_3Px8GPU_multimedia_rerun/) | re-run of `3Dx8GPU_3Px8GPU_multimedia_baseline` | Qwen3-VL-235B-A22B | 3D×8GPU / 3P×8GPU | coord TTFT 4-8× higher (prefill queue bottleneck) |
| [3Dx8GPU_3Px8GPU_multimedia_active_request_scorer](3Dx8GPU_3Px8GPU_multimedia_active_request_scorer/) | coord re-run w/ active-request-scorer | Qwen3-VL-235B-A22B | 3D×8GPU / 3P×8GPU | prefill bottleneck resolved; coord ≈ sidecar |
| [4Dx2GPU_3Px2GPU_multimedia_burst_baseline](4Dx2GPU_3Px2GPU_multimedia_burst_baseline/) | multimodal burst 4-128, 3 images | Qwen3-VL-32B | 4D×2GPU / 3P×2GPU | coord ≈ sidecar within ±10% at every burst |
| [4Dx2GPU_3Px2GPU_multimedia_burst_constrained](4Dx2GPU_3Px2GPU_multimedia_burst_constrained/) | multimodal burst 8-256, 1-5 images, decode cliff | Qwen3-VL-32B | 4D×2GPU / 3P×2GPU (`--max-num-seqs=8`) | coord ≈ sidecar within ±3% at deep queueing |
| [2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer](2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer/) | asymmetric decode fleet + multi-scorer | Qwen3-VL-32B | 2 fast+2 slow D / 3P | **coord wins tail at burst 64/256** |
| [bench11.1_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer](bench11.1_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer/) | re-run of 2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer with sglang request-body fixes | Qwen3-VL-32B | 2 fast+2 slow D / 3P | **coord wins tail at burst 64/128/256** |
| [bench11.2_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_v4_routing_trace](bench11.2_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_v4_routing_trace/) | re-run w/ EPP `--v=4` routing trace | Qwen3-VL-32B | 2 fast+2 slow D / 3P | **coord wins tail; routing skew fast↑ observed** |
| [sglang-bench-patch-with-burst8](sglang-bench-patch-with-burst8/) | ITL measurement fix, sidecar only | Qwen3-VL-32B | 4D×2GPU / 3P×2GPU | sglang ITL 3× inflation explained (request-body fix suffices) |

---

## Per-benchmark details

### bench1-2_var_output_always_disaggr

**Purpose.** Coord vs sidecar with input fixed at 250 tokens and output
length varying (100 / 500 / 1000 / 2500 / 5000). Isolates decode cost
by holding prefill constant.

**Harness.** `inference-perf` v0.5.2, per-step configs
`config_250_{100,500,1000,2500,5000}.yaml`. Each step: 120 requests,
`num_workers: 1`, `worker_max_concurrency: 1`, streaming, `ignore_eos: true`.
Rate/duration: 100→1 req/s / 120s, 500→0.5 / 240s, 1000→0.25 / 480s
(2500/5000 steps corrupted or truncated — excluded).

**Cluster stack.**
- Model `openai/gpt-oss-120b`, streaming completion API.
- Coord namespace `dpikus-epd`, gateway `http://10.16.2.183:80`.
- Sidecar namespace `dpikus-pd`.
- Topology: 1 decode pod, 1 prefill pod on each side (no explicit
  node pinning — decode/prefill pod placement was free, which turned
  out to matter — see next bench).

**Finding.** Coord ~7-8% slower on decode-per-token. Later shown in
`bench1-2_pinned` and `bench1-3` that this gap is a
node-hardware-variance artifact, not a real architectural difference.

### bench1-2_var_output_always_disaggr_pinned

**Purpose.** Rerun of `bench1-2_var_output_always_disaggr` with all
components (gateway, EPP, coord, decode, prefill) explicitly pinned to
the same physical nodes on both coord and sidecar sides, to eliminate
node-hardware variance.

**Harness.** Same as `bench1-2_var_output_always_disaggr`, plus a fourth
step at 2500 tokens (0.1 req/s / 1200s).

**Cluster stack.**
- Same as `bench1-2`, plus `nodeSelector` pinning: gateway `g49fc0a`,
  EPP `g49fc0a`, coordinator (coord only) `g801c7a`, decode `gf2a19e`,
  prefill `gc37d06` — identical physical nodes for coord and sidecar.

**Finding.** With node placement matched, all four output-length steps
show coord and sidecar within ~1% on latency, TTFT, ITL, and throughput
(120/120 success). The `bench1-2` gap was node variance.

### bench1-2_var_prompt_always_disaggr

**Purpose.** Coord vs sidecar with output fixed at 250 tokens and input
length varying (1 / 10 / 100 / 1000 / 10000). Sidecar's EPP
`nonCachedTokens: 0` forces always-disaggregation (matches coord's
default behavior).

**Harness.** `inference-perf` v0.5.2, per-step configs
`config_{1,10,100,1000,10000}_250.yaml`. 120 requests / step, streaming.
Rate/duration: 1-10→1 req/s / 120s, 100→0.5 / 240s, 1000→0.25 / 480s,
10000→0.1 / 1200s. Also a `config_10000_250_TP-4.yaml` variant for the
matched-TP experiment (both prefill and decode TP=4).

**Cluster stack.**
- Model `openai/gpt-oss-120b`, streaming.
- Coord namespace `dpikus-epd`; sidecar namespace `dpikus-pd`.
- 1D / 1P per side. Sidecar EPP configured `nonCachedTokens: 0` so
  every request disaggregates (matching coord's structural behavior).

**Finding.** Coord ~7-8% slower on latency/ITL at 1-1000 tokens,
converging at 10000. The gap is later attributed to node variance in
`bench1-3`. Also documents a NIXL/UCX connector cache bug encountered
during earlier attempts.

### bench1-3_var_prompt_always_disaggr

**Purpose.** Repeat of the input-length sweep from `bench1-2` with two
changes: output cut to 20 tokens (avoids the `worker_max_concurrency: 1`
rate cap), and prefill/decode pinned to the same node pair on both
architectures (prefill `gc37d06`, decode `gf2a19e`).

**Harness.** `inference-perf`, configs `config_{1,10,100,1000}_20.yaml`.

**Cluster stack.**
- Model `openai/gpt-oss-120b`, streaming, `ignore_eos: true`, OT=20.
- 1D / 1P per side, pinned nodes identical for coord and sidecar.

**Finding.** Once nodes are pinned, coord ≈ sidecar on ITL (within 0.7%
at every size). The only surviving gap is a small consistent TTFT
difference (coord ~2-5% higher) and wider coord ITL spread (p90-p10
~2-3× sidecar's). The `bench1-2` decode gap was a node artifact.

### 1D_1P_250IT_5000OT_decode_heavy

**Purpose.** Decode-heavy shape (short input, very long output).
Single-stream (serial requests) latency comparison.

**Harness.** `inference-perf`, single config, 250 IT / 5000 OT fixed,
120 requests, 0.25 req/s configured but effectively serial
(`worker_max_concurrency: 1` + ~34 s per request → delivered ~0.029 req/s).

**Cluster stack.**
- Model `openai/gpt-oss-120b`, streaming.
- Namespaces `dpikus-epd` (coord) / `dpikus-pd` (sidecar).
- 1D / 1P per side (implicit — same stack as bench1).

**Finding.** Coord wins by ~7% end-to-end (33.9s vs 36.5s), entirely
from lower TPOT (6.78 vs 7.28 ms/tok). TTFT is a tie. The mirror image
of light bench1: workload is decode-bound so the coord's faster
per-token streaming wins.

### 2D_8P_5000IT_250OT_prefill_heavy

**Purpose.** Prefill-heavy shape at saturating rate. Same 5000/250 shape
as an earlier bench2 (0.25 req/s tie) but at ~170× the load.

**Harness.** `inference-perf`, constant 45 req/s × 120 s = 5400
requests, `num_workers: 45`, `worker_max_concurrency: 100`.

**Cluster stack.**
- Model `openai/gpt-oss-120b`, streaming.
- **2 decode pods + 8 prefill pods** per side.
- Namespaces `dpikus-epd` (coord) / `dpikus-pd` (sidecar).

**Finding.** Sidecar wins under load — TTFT p99 21.9% lower, request
latency p99 16.3% lower; medians close (~1.5%). TPOT is a dead tie.
Coord's serialized cross-pod prefill hop queues under contention
(prefill-leg p99 ~9.1 s from coordinator.log).

### 3D_8P_250IT_4000OT_decode_heavy

**Purpose.** Decode-heavy, high-concurrency shape below the saturation
knee, with a horizontally-scaled coordinator.

**Harness.** `inference-perf`, target 10 req/s, 1200 requests, gaussian
ISL ≈ 257 / OSL ≈ 3910 (nominal 250 / 4000), streaming.

**Cluster stack.**
- Model `openai/gpt-oss-120b`, streaming.
- **3 decode pods + 8 prefill pods** per side.
- **Coord runs 3 coordinator replicas** (horizontally scaled).
- Namespaces `dpikus-epd` (coord) / `dpikus-pd` (sidecar).

**Finding.** Both architectures perform-equivalent (~0.5% end-to-end
gap; only a 6-17 ms TTFT overhead across percentiles). Load evenly
distributed across 3 coord replicas (400/400/401 completions).

### 3Dx8GPU_3Px8GPU_multimedia_baseline

**Purpose.** First multimodal (image+text) coord-vs-sidecar comparison.

**Harness.** `sglang.bench_serving` (`sglang-oai-chat` backend), Job on
cluster. Concurrency sweep 10/20/30/40, `--num-prompts=<c>`,
`--request-rate=<c>`, 1080p, `--image-count=3`, IT=300 tok, OT=2000 tok,
`ignore_eos` off (real generation).

**Cluster stack.**
- Model `Qwen/Qwen3-VL-235B-A22B-Instruct`.
- **3 prefill pods + 3 decode pods per side, each 8 GPUs (TP=8)**.
- Coord adds an unused `coordinator-epd-encode-epp` and an
  `--ec-transfer-config` on prefill (encoder-cache wiring, dormant).
- Sidecar adds `--disable-access-log-for-endpoints`.
- Namespaces `dpikus-epd-sglang-bench` / `dpikus-pd-sglang-bench`.

**Finding.** Sidecar ~2-2.3× faster end-to-end; TTFT 3-14× lower. The
coordinator's dispatch logic itself is fast (sub-10 ms), but its
prefill-pod selection funnels concurrent image-heavy requests onto one
GPU. See `3Dx8GPU_3Px8GPU_multimedia_rerun` and `3Dx8GPU_3Px8GPU_multimedia_active_request_scorer` for follow-ups.

### 3Dx8GPU_3Px8GPU_multimedia_rerun

**Purpose.** Re-run of `3Dx8GPU_3Px8GPU_multimedia_baseline` with
`analysis/` added, deeper instrumentation, cross-check of TTFT numbers
against coord's own logs.

**Harness.** Same as `3Dx8GPU_3Px8GPU_multimedia_baseline`.

**Cluster stack.** Same as `3Dx8GPU_3Px8GPU_multimedia_baseline`. 3D +
3P per side, TP=8 per pod.

**Finding.** Confirms the baseline result: coord's prefill leg runs to median
40s / p90 87.5s (3Dx8GPU_3Px8GPU_multimedia_rerun numbers), meaning prefill pods are
independently generating a full response worth of tokens each request
(~878 tok/req vs sidecar's ~2 tok/req) — a functional defect in coord's
disaggregation on this workload/topology.

### 3Dx8GPU_3Px8GPU_multimedia_active_request_scorer

**Purpose.** Coord-only re-run of `3Dx8GPU_3Px8GPU_multimedia_rerun` with
`active-request-scorer` enabled in coord's EPP scheduling profile.
Sidecar side is byte-identical to `3Dx8GPU_3Px8GPU_multimedia_rerun/sidecar/` (baseline).

**Harness.** Same as `3Dx8GPU_3Px8GPU_multimedia_rerun`.

**Cluster stack.** Same as `3Dx8GPU_3Px8GPU_multimedia_rerun`, but with the coord's decode-EPP
`schedulingProfile.default` using `active-request-scorer` (weight 1).

**Finding.** With the scorer in effect, coord's prefill-pool queueing
collapses (median ~sub-second across 225 pooled requests). TTFT, E2E,
TPOT, ITL now all within single-digit-to-mid-teens % of sidecar at
every concurrency level. The
`3Dx8GPU_3Px8GPU_multimedia_baseline`/`3Dx8GPU_3Px8GPU_multimedia_rerun` prefill bottleneck was
the scoring, not the topology.

### 4Dx2GPU_3Px2GPU_multimedia_burst_baseline

**Purpose.** First burst-sweep stress test of coord's "deferred decode"
placement. Small-model, high burst, variable prefill duration.

**Harness.** `sglang.bench_serving`, Job on `turin-gp`,
`BURST_SIZES=(4 8 16 32 64 128)`, `--request-rate=1000` (instantaneous
burst), `--num-prompts=<burst>`, IT=300, OT=2000, 3 fixed images per
request, 60 s quiesce between bursts.

**Cluster stack.**
- Model `Qwen/Qwen3-VL-32B-Instruct`.
- **4 decode pods × 2 GPU each (TP=2) + 3 prefill pods × 2 GPU each (TP=2)**.
- Decode: `--block-size=128`, NIXL kv-transfer, `--no-disable-hybrid-kv-cache-manager`.
- Namespaces `dpikus-epd-sglang-bench` / `dpikus-pd-sglang-bench`.

**Finding.** Coord ≈ sidecar within ±10% at every burst — the deferred
-decode hypothesis is not supported by these numbers on this fleet.

### 4Dx2GPU_3Px2GPU_multimedia_burst_constrained

**Purpose.** Retry of 4Dx2GPU_3Px2GPU_multimedia_burst_baseline's deferred-decode hypothesis under
conditions specifically constructed to expose it: hard decode capacity
cliff plus real per-request prefill variance.

**Harness.** `sglang.bench_serving`, `BURST_SIZES=(8 16 32 64 128 256)`,
1-5 images per request via `--random-image-count`, IT=300, OT=2000,
`seed=42` on both sides. Instantaneous burst arrival.

**Cluster stack.**
- Model `Qwen/Qwen3-VL-32B-Instruct`.
- **Decode: 4 replicas × 2 GPU (TP=2), `--max-num-seqs=8`,
  `--max-num-batched-tokens=4096`** — fleet-wide decode budget 32 slots.
- **Prefill: 3 replicas × 2 GPU (TP=2)**, stock knobs.
- Pod anti-affinity: decode and prefill on different nodes.
- Both EPPs' decode `schedulingProfile.default`:
  `active-request-scorer` (weight 1) only.

**Finding.** Coord ≈ sidecar within ±3% at every deep-queueing burst
(64/128/256). Deferred-decode hypothesis still not supported: with
`active-request-scorer` alone on both sides, the timing difference
between "at arrival" (sidecar) and "after prefill" (coord) never
resolves into a load-placement difference.

### 2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer

**Purpose.** Expose deferred-decode's advantage by making D-pool load
state *observable* to a metrics-based scorer, on an *asymmetric* decode
pool that the naive scorer can't reason about.

**Harness.** Same burst sweep as `4Dx2GPU_3Px2GPU_multimedia_burst_constrained`: `(8 16 32 64 128 256)`,
`--num-prompts=<burst>`, `--request-rate=1000`, 1-5 images
(`--random-image-count`), IT=300, OT=2000, `seed=42`. Only
`--extra-request-body '{"ignore_eos": true}'` (sglang measurement bugs
not yet fixed here).

**Cluster stack.**
- Model `Qwen/Qwen3-VL-32B-Instruct`.
- **Asymmetric decode pool (24 slots total)**:

  | variant | replicas | `--max-num-seqs` | slots | label |
  |---|---:|---:|---:|---|
  | fast | 2 | 8 | 16 | `llm-d.ai/variant=fast` |
  | slow | 2 | 4 | 8 | `llm-d.ai/variant=slow` |

  Fast/slow share the same InferencePool selector labels
  (`role=decode`), so a single pool sees all 4 pods.
- Prefill: **3 replicas per side, `--max-num-seqs` unset**.
- **Both EPPs run a 3-scorer stack**:
  ```yaml
  plugins:
  - pluginRef: kv-cache-utilization-scorer   # weight 3
  - pluginRef: queue-scorer                  # weight 2
  - pluginRef: active-request-scorer         # weight 1
  ```
  Plus `metrics-data-source` and `core-metrics-extractor` as data
  sources for the metrics scorers (reading vLLM's `/metrics`).
- Namespaces `dpikus-epd-sglang-bench` / `dpikus-pd-sglang-bench`.

**Finding.** **Coord (deferred decode) beats sidecar (early-bind) at
burst 64 and 256** on TTFT p90 / E2E p90 (−24.8% / −19.6% at 64;
−7.7% / −7.2% at 256). Medians and TPOT tied. First bench that
reproduces a deferred-decode advantage.

### bench11.1_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer

**Purpose.** Re-run of `2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer` with sglang-bench request-body fixes
(validated in bench13/`sglang-bench-patch-with-burst8`):

```
--extra-request-body '{"ignore_eos": true, "skip_special_tokens": false, "stream_options": {"include_usage": true}}'
```

**Cluster stack.** Byte-identical to `2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer` (verified via
`diff -r` on bench_config; same EPP ConfigMaps).

**Finding.** Coord edge extends into burst 128 (E2E p90 −11.4%,
TTFT p90 −13.6%), plus burst 64 (E2E p90 −14.1%) and burst 256
(throughput +5.7%). Same direction as `2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer`; deferred-decode
advantage confirmed reproducible.

### bench11.2_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_v4_routing_trace

**Purpose.** Third repeat of `2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer` with **all three EPPs patched to
`--v=4`** so each request's picked decode-pod IP is logged
(`"Request handled" endpoint=<pod-IP>:8000`). Adds direct routing
observation to the deferred-decode analysis.

**Cluster stack.** Same fleet as `bench11.1`. EPPs
(`coordinator-epd-decode-epp`, `coordinator-epd-prefill-epp`,
`pd-disaggregation-epp`) patched to `--v=4` for this run only;
gateway rollout-restarted after the patch so Envoy's ExtProc filter
re-attaches to the new EPP pod. Logs streamed live via `kubectl logs -f`
into local files (default container-log rotation would have truncated
the log at V(4)).

**Finding.** Same tail-latency wins as `bench11.1`
(TTFT p90 −23.3% at 64, −14.6% at 128, −11.1% at 256). Routing analysis
in `analysis/ROUTING_MECHANISM.md`: **sidecar routes 50/50 fast:slow;
coord skews 53-67% toward fast pods** — direction-consistent with the
p90 win, mechanically explained by coord picking decode target after
prefill (when per-pod KV pressure/queue depth is observable).

### sglang-bench-patch-with-burst8

**Purpose.** Improve the accuracy of ITL measurement in
`sglang.bench_serving` v0.5.14 under concurrency. Earlier work had shown
wire-level ITL of ~12 ms while the tool reported ~31 ms — suspected as
a `time.perf_counter()`-scheduling issue in the consumer coroutine,
lagging actual wire arrival under concurrency. In the end the patch
itself does not resolve that gap; the observed improvement from the
patch alone is small (no more than ~3%). The dominant correction turns
out to be a request-body change, not the code — see Finding below.

**Harness.** Two fixes applied and compared:
1. `bench_serving.py` patch — timestamp each SSE chunk in aiohttp's
   `on_response_chunk_received` trace hook (patched file:
   `sidecar/bench_config/bench_serving_patched.py`,
   diff: `sidecar/bench_config/bench_serving.patch`).
2. Request body: `skip_special_tokens: false` +
   `stream_options.include_usage: true`.

Only the **sidecar side** was run; this is a measurement-methodology
bench, not a coord-vs-sidecar comparison. Fixed workload: burst=8, 2000
output tokens, same model/fleet as 4Dx2GPU_3Px2GPU_multimedia_burst_baseline/4Dx2GPU_3Px2GPU_multimedia_burst_constrained.

**Cluster stack.**
- Model `Qwen/Qwen3-VL-32B-Instruct`, sidecar side only.
- **4 decode pods × 2 GPU (TP=2)** + prefill (see `decode.yaml`).
- Bench Job mounts patched `bench_serving.py` from a ConfigMap and
  copies it over the installed file at container startup; `ast.parse`
  validates before overwrite; `inspect.getsource` verifies after import.

**Finding.** The **request-body fix alone** is sufficient — setting
`skip_special_tokens: false` moves empty-content SSE events from 44%
to <1%, which drives Mean ITL from ~25 ms to ~12 ms via sglang's
arithmetic (`(E2E-TTFT)/(N-1)`). The `bench_serving.py` patch is only
load-bearing when empty-content deltas can't be avoided or when ITL
*shape* (p50, tail) matters. This finding is the basis for the
request-body change adopted in `bench11.1`.

---

## Reading the summaries

Each bench's `SUMMARY.md` contains: (1) the exact workload shape, (2)
per-step or per-burst results in tables, (3) coord-vs-sidecar deltas,
(4) data-validation notes (pod-log spot checks, error counts), and (5) a
"Reading it" / "Bottom line" section interpreting the numbers. Where
present, `PLAN.md` records the design rationale (why this bench was
constructed) before the results came in, and `analysis/` holds
supporting charts, notebooks, or per-request cross-checks.
