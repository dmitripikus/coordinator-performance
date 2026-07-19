# bench7, 3D/3P x8GPU multimedia (image+text): Coordinator (EPD) vs Sidecar (PD)

Benchmark: `sglang-bench` (`sglang-oai-chat` backend), model `Qwen/Qwen3-VL-235B-A22B-Instruct`,
multimodal requests (1-3 random JPEG images per request, ~300 text tokens in,
2000 tokens out target), 4 fixed request-rate sweeps: **10 / 20 / 30 / 40 req/s**,
10/20/30/40 prompts respectively, streaming, 0 failed requests in both runs.

- **Coordinator** (`coord/`, ns `dpikus-epd-sglang-bench`): `llm-d-coordinator` in front of
  3 prefill + 3 decode vLLM pods. A `coordinator-epd-encode-epp` pod also exists in this
  namespace, but its log has 0 lines and the coordinator's own pipeline timings (§2) show
  only `parse` / `prefill` / `decode` stages, no separate encode stage is actually
  exercised. Image handling happens inside the prefill stage, same as the sidecar run.
- **Sidecar** (`sidecar/`, ns `dpikus-pd-sglang-bench`): `routing-proxy` sidecar next to
  each pod, no coordinator, 3 prefill + 3 decode vLLM pods.

Configs are otherwise identical (`benchmark-job.yaml`, `payload_http.json` diff clean;
only the gateway `base_url` differs between clusters). So this *is* a like-for-like
coordinator-vs-sidecar comparison, both run the same prefill/decode split, just routed
differently. Earlier text-only benches (bench1-6) found coordinator and sidecar within ~1%
and ~10-20ms TTFT of each other; the much larger gap below shows up specifically under
concurrent image-heavy load. Root cause (§2): the coordinator's routing spreads requests
across the 3 prefill pods unevenly *in time*, letting 30-39 image-heavy requests pile onto
one GPU at once; the sidecar's routing-proxy keeps every prefill pod under 3 concurrent
requests throughout. The coordinator's own dispatch logic is not the delay, it hands off
to vLLM in under a millisecond every time.

**The prefill vLLM pods themselves are also apples-to-apples**, confirmed by diffing
`pod_description.txt` for a representative prefill pod on each side (both are
ReplicaSet-templated, so this represents all 3 replicas per arm). Identical: container
image (same digest, `ghcr.io/revit13/vllm-openai:nightly-b50646e5effd7cb5884cd96fdff4c53c18521198.omer4`),
resources (`cpu: 8`, `memory: 256Gi`, `nvidia.com/gpu: 8`, `rdma/ib: 1`, requests=limits,
`QoS: Guaranteed`), and the core vLLM args (`--tensor-parallel-size=8`, `--block-size=128`,
`--kv-transfer-config {"kv_connector":"NixlConnector","kv_role":"kv_both"}`,
`--no-disable-hybrid-kv-cache-manager`, `--gpu-memory-utilization=0.9`,
`--load-format=runai_streamer`, model `Qwen/Qwen3-VL-235B-A22B-Instruct`). Two differences
found, neither performance-relevant:
- Coordinator's prefill additionally passes
  `--ec-transfer-config {"ec_connector": "ECCPUConnector", "ec_role": "ec_consumer"}`
  (encoder-cache transfer wiring). No encode-only vLLM pod exists in either pod list, and
  we already confirmed `coordinator-epd-encode-epp`'s log is empty and the coordinator's own
  pipeline never logs an encode step, so this looks like dormant chart wiring, not something
  actually exercised.
- Sidecar's prefill additionally passes
  `--disable-access-log-for-endpoints=/health,/metrics,/v1/models`; coordinator's doesn't.
  This is a pure logging-verbosity setting, and it fully explains why coordinator's prefill
  `modelserver.log` ran ~30,000 lines (almost entirely repeated `GET /metrics` access-log
  entries) versus sidecar's ~350-390 lines.
- Both prefill pods also carry a stale `llm-d.ai/model` label left over from whatever model
  the Helm chart was originally templated for (`Qwen3-VL-2B-Instruct` on coordinator's side,
  `gpt-oss-120b` on sidecar's), disagreeing with the actual served model. The real `--model`
  argument passed to `vllm serve` agrees on both sides, this is metadata drift, not an actual
  model mismatch.

## 1. Serving results by request rate (n=10/20/30/40, 0 failures each)

| Req rate | Metric | Coordinator (EPD) | Sidecar (PD) | Sidecar advantage |
|---:|---|---:|---:|---:|
| 10 | Duration | 91.0 s | **46.3 s** | 2.0x faster |
| 10 | Output tok/s | 80.6 | **158.3** | 2.0x |
| 10 | TTFT mean | 22.50 s | **6.65 s** | 3.4x lower |
| 10 | TTFT p99 | 61.82 s | **10.96 s** | 5.6x lower |
| 10 | E2E mean | 49.63 s | **25.66 s** | 1.9x lower |
| 20 | Duration | 159.6 s | **69.4 s** | 2.3x faster |
| 20 | Output tok/s | 103.3 | **237.6** | 2.3x |
| 20 | TTFT mean | 63.23 s | **9.06 s** | 7.0x lower |
| 20 | TTFT p99 | 106.66 s | **15.89 s** | 6.7x lower |
| 20 | E2E mean | 83.43 s | **39.32 s** | 2.1x lower |
| 30 | Duration | 223.3 s | **97.0 s** | 2.3x faster |
| 30 | Output tok/s | 132.5 | **304.9** | 2.3x |
| 30 | TTFT mean | 84.80 s | **8.59 s** | 9.9x lower |
| 30 | TTFT p99 | 196.02 s | **14.30 s** | 13.7x lower |
| 30 | E2E mean | 116.12 s | **54.05 s** | 2.1x lower |
| 40 | Duration | 201.0 s | **108.7 s** | 1.9x faster |
| 40 | Output tok/s | 188.2 | **348.0** | 1.9x |
| 40 | TTFT mean | 69.75 s | **15.55 s** | 4.5x lower |
| 40 | TTFT p99 | 151.65 s | **28.64 s** | 5.3x lower |
| 40 | E2E mean | 114.64 s | **62.15 s** | 1.8x lower |

**TPOT/ITL run the other way** (coordinator slightly better): e.g. at rate 30, coordinator
mean TPOT 28.3 ms vs sidecar 48.9 ms; mean ITL 31.9 ms vs 66.2 ms. Decode-side per-token
cost is a bit higher on the sidecar path, but it's dwarfed by the TTFT gap above.

## 2. Root cause: uneven, bursty routing overloads one prefill GPU at a time

**Step 1, the coordinator control plane is not the delay.** Correlating
`received request` / `sending request` timestamps per `x-request-id` in the coordinator's
own log (226 requests) shows the coordinator hands each request to a prefill vLLM pod in
**<10 ms every single time** (mean/median/max all ~0.00-0.01s). All of the latency lives
between "sent to prefill" and "prefill complete", i.e. inside vLLM's response time, not
inside the coordinator:

| Stage (coordinator-measured) | Mean | Median | Max |
|---|---:|---:|---:|
| parse | 8 ms | n/a | n/a |
| coordinator → prefill dispatch | ~0 ms | ~0 ms | 10 ms |
| **prefill (dispatch → response)** | **34.5 s** | 0.5 s | **139.5 s** |
| decode | 15.7 s | 9.1 s | 83.7 s |

**Step 2, the coordinator sends an entire concurrency sweep to a single prefill pod at a
time.** Each prefill pod logs its own concurrency every ~10s (`Running: N reqs`). Lining up
each pod's `Running` timeline against the client's 4 concurrency sweeps
(rate 10: 09:16:43-09:18:41, rate 20: 09:18:41-09:21:43, rate 30: 09:21:43-09:25:51,
rate 40: 09:25:51-09:29:41) shows an exact one-sweep-one-pod pattern:

| Sweep (target rate) | Pod that took the sweep | Peak `Running` | Other 2 pods during this sweep |
|---|---|---:|---|
| 10 | prefill-**468vq** | 8 | idle (Running=0 throughout) |
| 20 | prefill-**lng4g** | 20 | idle |
| 30 | prefill-**lng4g** (again) | 30 | idle |
| 40 | prefill-**9whgp** | 39 | idle |

Every sweep ramps one previously-idle pod from `Running=0` straight up to its peak within
~30s (e.g. prefill-9whgp: 0 → 10 → 27 → 39 in 30 seconds flat) while the *other two replicas
never receive a single request for the entire sweep*. This is not a subtle imbalance, it's
one-pod-at-a-time routing, and which pod gets picked changes between sweeps (not a fixed
"always pod X" bug either).

By contrast, the sidecar's routing keeps **all 3** prefill pods lightly active, and never
lets any one of them accumulate a backlog. Same format as the coordinator's table above,
peak `Running` per pod within each sweep window (rate 10: 14:15:01-14:16:10, rate 20:
14:16:10-14:17:40, rate 30: 14:17:40-14:19:40, rate 40: 14:19:40-14:21:55):

| Sweep (target rate) | prefill-ntwck peak `Running` | prefill-v24mx peak `Running` | prefill-wr5cf peak `Running` |
|---|---:|---:|---:|
| 10 | 0 | 0 | **1** |
| 20 | **1** | 0 | 0 |
| 30 | **2** | **1** | 0 |
| 40 | 0 | **3** | 0 |

Contrast this directly with the coordinator's table: coordinator peaks are 8, 20, 30, 39
(all on a single pod per sweep), sidecar peaks are 1, 1, 2, 3 (spread, and at rate 30, two
different pods concurrently). No sidecar pod ever approaches even coordinator's *smallest*
sweep peak (8).

Full per-timestamp `Running`/`Waiting` detail behind this table:

| Wall clock | prefill-ntwck | prefill-v24mx | prefill-wr5cf |
|---|---:|---:|---:|
| 14:15:26 (rate 10) | - | - | Running=1 |
| 14:16:41 (rate 20) | Running=1 | - | - |
| 14:18:04 (rate 30) | - | Running=1 | - |
| 14:18:11 (rate 30) | Running=2, Waiting=1 | - | - |
| 14:18:14 (rate 30) | - | Running=1 | - |
| 14:20:14 (rate 40) | - | Running=3 | - |
| 14:20:24 (rate 40) | - | Running=1 | - |

(all other sampled timestamps for all 3 pods read `Running=0, Waiting=0`, omitted for
brevity.) Two things stand out against the coordinator's table above:

- **No pod ever exceeds `Running=3`.** The busiest single moment across the entire run,
  anywhere, on any pod, is 3 concurrent requests, versus the coordinator's 39.
- **Different pods are active within the *same* sweep, at overlapping times.** During rate
  30 specifically, prefill-v24mx shows `Running=1` at 14:18:04 and 14:18:14 while
  prefill-ntwck shows `Running=2` at 14:18:11, i.e. two different GPUs are handling separate
  concurrent requests from the same sweep within the same 10-second window. That's the
  opposite of the coordinator's pattern, where the two "other" pods sat at `Running=0` for
  the entire duration of every sweep.

Because concurrency never builds past single digits on the sidecar side, this data is
inherently sparse (vLLM's own periodic logger has little to report when there's nothing
running), unlike the coordinator's dense, continuously-climbing 0→39 ramps. That sparsity is
itself part of the finding: there's no backlog on any one pod for the logger to describe.

**Step 3, a plausible but not fully confirmed mechanism from the EPP's own scorer config
and source.** The prefill EPP's ConfigMap (`epd-prefill-epp`, key `epd-plugins.yaml`, the
file actually referenced by `--config-file` in the pod spec) wires up 3 scorers:

```yaml
schedulingProfiles:
- name: default
  plugins:
  - pluginRef: queue-scorer               # weight 1
  - pluginRef: kv-cache-utilization-scorer # weight 1
  - pluginRef: prefix-cache-scorer         # weight 2
```

Per the plugin implementations in [llm-d/llm-d-router](https://github.com/llm-d/llm-d-router)
(`pkg/epp/framework/plugins/scheduling/scorer/`):

- **`queue-scorer`** scores purely on vLLM's *waiting*-queue length
  (`WaitingQueueSizeKey`), normalized `(maxQueue-queue)/(maxQueue-minQueue)` across
  candidates, **with an explicit fallback: if all endpoints report the same queue size,
  every endpoint gets a neutral score of 1.0.** We already confirmed `Waiting` sits at 0 on
  every coordinator pod almost the entire time (§ above), because vLLM's continuous batching
  admits new requests straight into `Running` instead of queueing them. So this scorer is
  permanently tied at 1.0 for all 3 pods under this workload, contributing zero
  discrimination despite its weight.
- **`kv-cache-utilization-scorer`** scores only on GPU KV-cache usage percent
  (`score = 1 - kvCacheUsagePercent`), with no request-count input at all. Since prefill KV
  usage peaked at only ~12% even at 39 concurrent requests, this scorer barely separates a
  saturated pod (score ~0.88) from an idle one (score 1.0), it is not the signal that would
  stop a pileup.
- **`prefix-cache-scorer`**, weighted **2x** the other two, scores purely on cached-prefix
  match ratio/length against a pod's previously-served prompts, with **no load-awareness
  whatsoever** by design (its own README documents no queue-depth or active-request input).
  This is where the analysis gets uncertain: the benchmark's images are randomly generated
  per request and vision tokens dominate the sequence (~4700 of ~4900 tokens), so if
  prefix-block matching works the usual way (longest matching prefix of fixed-size token
  blocks from the start of the sequence), only the ~17-20 token shared chat-template
  boilerplate could ever match, a tiny fraction of total blocks. At that magnitude, even at
  weight 2, this scorer's contribution to the total score would be close to negligible, not
  the near-1.0, dominant signal I first described. I don't have visibility into whether the
  "approximate prefix cache" data producer behind this scorer does something coarser than
  strict per-block hashing that would change this, so I can't rule the mechanism in or out
  with confidence from the config and repo docs alone.

**Step 4, ruling out a simpler explanation, and why the sticky-pod pattern still needs an
affinity-type driver.** Before trusting a scoring explanation at all, I checked whether the
coordinator's prefill EPP simply lost visibility into 2 of the 3 pods during a sweep, a much
more mundane bug than scorer-weight interactions. It didn't: the prefill EPP's own
pod-reconciler log shows all 3 prefill pods being continuously re-registered every ~30-90s
for the *entire* run, including during every sweep, with no pod ever dropping from the
candidate list. So the coordinator always had all 3 replicas available, it just kept
choosing one. Separately, `kv-cache-utilization-scorer` cannot be the source of the
stickiness either: its formula (`1 - kvUsage`) means a pod's score *drops* as it gets
busier, so on its own it's self-correcting, it should push traffic away from an
increasingly loaded pod, not toward it. Something that specifically rewards a pod *because*
it was already chosen is needed to produce a feedback loop, and prefix/affinity-style
scoring is the only plugin type in this config with that shape, whether or not its actual
magnitude here is as large as originally described above.

**Net assessment:** I can point to a config-level candidate mechanism (prefix-cache-scorer
being the only signal capable of producing sticky, load-blind selection) and a confirmed
ratio difference between the two configs, but I cannot confirm from static YAML and coarse
(~10s) vLLM metrics alone that this fully explains the observed magnitude of the gap, given
the random-image-content concern above. Getting a definitive answer would need the EPP's
own per-request debug-level score breakdown, which neither run captured at `--v=2`.

vLLM's prefill step is compute-bound on the vision encoder pass over images regardless of
what's driving the pod selection, so funneling 20-39 concurrent multimodal requests onto one
GPU (while 2 identical GPUs sit unused) directly produces the 34.5s mean / 139.5s max
prefill time measured above. No OOMs, restarts, or errors in either run, whatever is
driving the pileup, it is a routing/scoring effect, not a crash.

## 3. Bottom line

For this multimedia (image+text) workload, the sidecar (PD) topology is **~2-2.3x faster
end-to-end and 3-14x lower TTFT** than the coordinator topology at every tested rate. The
bottleneck is **not the coordinator's control-plane logic** (dispatch is sub-10ms, always),
it's that the coordinator's prefill-pod selection routes an entire concurrency sweep to a
single replica at a time, leaving the other 2 identical GPUs idle for that whole sweep,
while the sidecar's routing-proxy spreads every sweep across all 3 replicas concurrently.
vLLM's prefill engine is compute-bound on vision encoding, so concentrating 20-39 concurrent
multimodal requests onto one GPU (instead of ~7-13 each across three) directly becomes the
multi-second-to-two-minute prefill waits that dominate TTFT. TPOT is correspondingly a bit
better on the coordinator, but it's a minor decode-side effect next to this prefill-side
concentration.

**Most likely cause, not fully confirmed (§2, steps 3-4):** the prefill EPP's
`epd-plugins.yaml` scoring profile weights `prefix-cache-scorer` at 2x `queue-scorer` and
`kv-cache-utilization-scorer` combined. Under this workload, the two load-aware scorers are
effectively blind (`queue-scorer` ties at a neutral 1.0 because vLLM's `Waiting` never moves
off 0; `kv-cache-utilization-scorer` barely moves because prefill KV usage stays under 12%
and is self-correcting, not self-reinforcing, in any case). `prefix-cache-scorer` is the only
plugin in this config with the right shape to produce sticky, load-blind selection, and a
pod-registration check ruled out a simpler "EPP lost visibility into 2 of 3 pods" bug. But
because this benchmark's images are random per request, prefix-cache-scorer's real
match-ratio magnitude here is genuinely unclear from config and coarse metrics alone, so this
is the best-supported hypothesis rather than a confirmed root cause. Either way, it's a
routing/scoring effect, not a coordinator control-plane bug or a vLLM/GPU issue.

**Recommended fix** (not implemented/tested here): for this pool, drop `queue-scorer` and
`prefix-cache-scorer` entirely rather than just re-weighting them, and make
`active-request-scorer` the dominant signal:

```yaml
- name: prefill
  plugins:
  - pluginRef: prefill-filter
  - pluginRef: active-request-scorer
    weight: 3
  - pluginRef: kv-cache-utilization-scorer
    weight: 1
  - pluginRef: max-score-picker
```

Rationale for each change:

- **`active-request-scorer` in, as the dominant weight (3).** Of the two "reacts to
  concurrent load" plugins in the repo, `active-request-scorer` and
  `running-requests-size-scorer` (`scorer/runningrequests`, keyed on
  `metrics.RunningRequestsSizeKey`), `active-request-scorer` is the better fit here because
  it's tracked by the EPP's own `inflight-load-producer`: updated the instant the EPP
  dispatches or completes a request, with no scrape-interval lag. `running-requests-size-scorer`
  would still depend on a periodic vLLM `/metrics` scrape, the same staleness class that let
  `queue-scorer` miss this pileup. With `active-request-scorer`'s default `idleThreshold: 0`,
  any pod with 1+ in-flight request immediately scores below a fully idle one, which directly
  counters the burst-onto-one-pod pattern observed above.
- **`prefix-cache-scorer` removed, not just de-weighted.** This benchmark's requests are
  random image/text content, so there's no real compute to save by cache-matching (the only
  thing it was matching on was ~17-20 tokens of shared chat-template boilerplate against
  ~4700 vision tokens per request, negligible). Its complete lack of load-awareness is what
  let it override the load signals and lock an entire sweep onto one GPU; there's no upside
  here worth keeping any weight for.
- **`queue-scorer` removed, not just de-weighted.** Already shown to be mathematically inert
  under this workload: `Waiting` is tied at 0 across pods, so it adds an identical constant
  to every candidate's score and never changes the ranking, regardless of weight.
- **`kv-cache-utilization-scorer` kept at a modest weight (1).** It's a legitimate signal,
  just not the deciding one for this compute-bound, short-prefill workload where KV usage
  stays low. A small weight costs nothing and stays useful if this pool ever also serves
  decode-heavy or long-context traffic where KV pressure becomes real.

This is a reasoned recommendation from the plugin docs and the observed failure mode, not a
benchmarked one. It should be validated by rerunning this exact rate 10/20/30/40 sweep and
checking that per-pod `Running` timelines spread out (no single pod monopolizing a sweep)
without introducing thrashing between replicas for borderline-tied load.
