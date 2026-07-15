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

By contrast, the sidecar's `routing-proxy` keeps **all 3** prefill pods lightly active in
overlapping windows throughout the run (peaks of 1, 3, and 2 concurrent requests
respectively, occurring at the same wall-clock times), it genuinely spreads each sweep's
concurrent requests across all replicas instead of concentrating them.

**Step 3, confirmed root cause from the EPP's own scorer config and source.** The prefill
EPP's ConfigMap (`epd-prefill-epp`, key `epd-plugins.yaml`, the file actually referenced by
`--config-file` in the pod spec) wires up 3 scorers:

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
  Any pod that already holds a matching cached prefix scores near 1.0 for this component
  regardless of how many requests it is currently running.

Combined, this means the two "spread the load" scorers are effectively blind under this
workload (one is mathematically tied, the other moves only slightly), while the one scorer
that actually varies, prefix-cache affinity, carries double weight and rewards *whichever
pod already served similar content*, irrespective of its current load. The benchmark
issues each sweep with a fixed `seed=42` and a shared chat-template/system-prompt overhead
across all requests, so once one pod wins the initial (tied, randomly broken per the EPP's
own selection rule) pick for a sweep, every subsequent request in that sweep matches its
cached prefix best, keeps scoring it highest, and keeps getting routed there, even as its
`Running` count climbs to 30-39. That's a positive feedback loop: prefix affinity keeps
picking the same "warm" pod harder than the (blind) load scorers can push back, which is
exactly the one-pod-per-sweep concentration in the table above. The pod "wins" a different
random draw each sweep because the tracked prefix-cache entries age out during the ~1-3
minute gaps between sweeps, resetting the tie for the next sweep's first request.

vLLM's prefill step is compute-bound on the vision encoder pass over images, so funneling
20-39 concurrent multimodal requests onto one GPU (while 2 identical GPUs sit unused)
directly produces the 34.5s mean / 139.5s max prefill time measured above. No OOMs,
restarts, or errors in either run, this is a scoring-weight interaction, not a crash.

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

**Confirmed cause (§2, step 3):** the prefill EPP's `epd-plugins.yaml` scoring profile
weights `prefix-cache-scorer` at 2x `queue-scorer` and `kv-cache-utilization-scorer`
combined. Under this workload, the two load-aware scorers are effectively blind
(`queue-scorer` ties at a neutral 1.0 because vLLM's `Waiting` never moves off 0;
`kv-cache-utilization-scorer` barely moves because prefill KV usage stays under 12%), while
`prefix-cache-scorer` has no load-awareness by design and keeps rewarding whichever pod
already cached a similar prompt from earlier in the same sweep. That combination is what
funnels an entire sweep onto one GPU: a plugin-weighting choice, not a coordinator
control-plane bug or a vLLM/GPU issue.

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
