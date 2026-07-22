# bench10_4Dx2GPU_3Px2GPU_multimedia_burst_constrained — PLAN

Follow-up to `bench9_4Dx2GPU_3Px2GPU_multimedia_burst`, which produced
a null result (coord ≈ sidecar within ±10% on every metric, no
monotonic winner across the burst sweep). See
[../bench9_4Dx2GPU_3Px2GPU_multimedia_burst/SUMMARY.md](../bench9_4Dx2GPU_3Px2GPU_multimedia_burst/SUMMARY.md).

## Root-cause diagnosis of bench9's null result

Deferred-decode's theoretical win requires all three of these to hold:

1. Sidecar's early-D-bind must sometimes pick the wrong pod.
2. The wrong pick must actually *queue* the request (not just enlarge
   a batch on the wrong pod).
3. Deferred bind must have enough live info to pick better.

In bench9, condition (2) failed. With no `--max-num-seqs` set on the
decode vLLM containers, each pod's batch grows elastically — the 128
concurrent requests at burst 128 spread as ~32 per pod, well below
any hard cap, so extra requests joined existing batches instead of
queueing. LB mistakes were silently absorbed by vLLM's continuous
batching. Additionally condition (1) was likely weak — 3 fixed-count
1080p images per request produced a tight prefill-time distribution,
so arrival order and completion order were nearly the same.

## bench10 changes vs bench9

### Decode capacity cliff (fixes condition 2)

Both sides' `decode.yaml` now add:

```yaml
- --max-num-seqs=8
- --max-num-batched-tokens=4096
```

(Two-token form on coord to match its existing convention;
`=`-form on sidecar to match its convention. Both are valid vLLM
argument styles.)

**Total decode slots across the fleet: 4 pods × 8 seqs = 32.** Any
burst ≥ 32 forces requests to actually queue. This is the regime
where a wrong LB pick costs one full decode duration
(~24 s at 2,000 tok × 12 ms TPOT) rather than being papered over
by batch growth.

### Real prefill variance (strengthens condition 1)

`benchmark-job.yaml` on both sides changes:

- `IMAGE_COUNT=3` → `IMAGE_COUNT=5` **plus** `--random-image-count`
  on the sglang command line. With `--random-image-count` set,
  `IMAGE_COUNT` becomes the *maximum*; sglang samples uniformly in
  `[1, IMAGE_COUNT]` per request.
- Per-request prefill now varies ~5× (1 image vs 5 images) rather
  than being fixed. Completion order becomes genuinely uncorrelated
  with arrival order.

### Burst sweep centered on the cliff

`BURST_SIZES=(4 8 16 32 64 128)` → `BURST_SIZES=(8 16 32 64 128 256)`.
Dropped burst 4 (fully under capacity, contributes nothing new vs
burst 8) and added burst 256 (8× over cliff — a real stress point).

| burst | vs cliff (32 slots) | expected regime | role in the story |
|---:|---|---|---|
| 8   | 0.25×  | fully under cap, no queueing on either side | control |
| 16  | 0.5×   | still under cap | control |
| 32  | 1×     | cliff edge | first place any queueing appears |
| 64  | 2×     | 32 in flight, 32 queued | primary win zone for deferred-D |
| 128 | 4×     | deep queueing, KV pressure real | LB errors compound |
| 256 | 8×     | severe overload | tail behavior + graceful-degradation test |

## Expected fingerprint of a coord win

At burst 8/16 (below cliff): coord ≈ sidecar (nothing to
differentiate, both fit).

At burst 32 (cliff edge): coord starts to nose ahead on TTFT p90
because deferred bind can steer the marginal request to whichever D
pod freed a slot first, while sidecar committed at arrival.

At burst 64/128 (deep queue): the split widens. Look for:

- **Duration**: coord noticeably shorter (fewer wasted decode slots).
- **TTFT p50**: coord modestly lower.
- **TTFT p90/p99**: coord *substantially* lower — this is where the
  mis-placed sidecar requests land. If sidecar's early bind sends 2
  extra requests to one already-full D, those requests wait an
  entire decode duration (~24 s) longer than they would on an idle
  pod.
- **Output tok/s**: coord modestly higher (less wasted D capacity).
- **TPOT**: should remain nearly identical (decode speed doesn't
  care about which pod runs the request).
- **`pd-disaggregation-nvidia-gpu-vllm-decode-*/routing-proxy.log`**
  request counts should be highly uneven across the 4 sidecar D
  pods; the coord `coordinator.log` `pipeline step timings` should
  show balanced per-D routing.

At burst 256 (severe overload): both configs degrade; watch which
one degrades more gracefully. Coord should win on tail; sidecar may
even fail requests if the gateway timeout is exceeded.

## What "hypothesis dead" looks like

If bench10 also produces a null result (coord ≈ sidecar at bursts
32/64/128/256), that's strong evidence the coord/sidecar EPP-scorer
difference — not the deferred vs early bind timing — is the load-
bearing variable. In that case:

1. Read `bench9/sidecar/pod_logs_.../epp-configs/pd-disaggregation-epp.yaml`
   to see what scorer sidecar is configured with.
2. If sidecar already uses `active-request-scorer` or a live
   queue-depth scorer, the "stale arrival state" premise is wrong.
3. Move on to the noisy-neighbor experiment (deliberately slow one D
   pod) — that's the crispest way to force a difference that early
   bind *cannot* see.

## Setup steps to run bench10

**Prereq check**: coord and sidecar vLLM deployments are currently at
0 replicas (bench9 scaled them down). The new `decode.yaml` files need
to be applied *before* scaling up, otherwise scaling up will bring up
pods without the `--max-num-seqs` cap and you'd have to roll them.

### Apply the decode-cap deployment changes

Both sides need the modified `decode.yaml` applied to the cluster.
These files are full deployment manifests with the new args baked
into `.spec.template.spec.containers[].args`.

```bash
# Coord side
kubectl config set-context --current --namespace=dpikus-epd-sglang-bench
kubectl apply -f coord/bench_config/decode.yaml

# Sidecar side
kubectl config set-context --current --namespace=dpikus-pd-sglang-bench
kubectl apply -f sidecar/bench_config/decode.yaml
```

Neither namespace has decode pods running right now (replicas=0), so
`apply` won't cause a rollout — it just updates the Deployment spec.
When the skill scales up in Step 3, the new pods will already have
the cap in place.

To sanity-check the apply worked:

```bash
kubectl get deployment epd-nvidia-gpu-vllm-decode -n dpikus-epd-sglang-bench \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="modelserver")].args}' \
  | tr ',' '\n' | grep -E 'max-num'
# expect: "--max-num-seqs" then "8" then "--max-num-batched-tokens" then "4096"

kubectl get deployment pd-disaggregation-nvidia-gpu-vllm-decode -n dpikus-pd-sglang-bench \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="modelserver")].args}' \
  | tr ',' '\n' | grep -E 'max-num'
# expect: "--max-num-seqs=8", "--max-num-batched-tokens=4096"
```

### Run the coord side

```
/run-sglang-bench pd-comparison-analysis/bench10_4Dx2GPU_3Px2GPU_multimedia_burst_constrained/coord/bench_config
```

Skill will detect the 0/0 topology and prompt to scale to 4/3 —
answer yes. The scaled-up pods will honor the new `--max-num-seqs=8`
because the Deployment spec was updated in the previous step.

Sweep is 6 bursts × ~30–120 s each + 60 s quiesce between = roughly
15–20 min. Burst 256 will take longer than any bench9 burst because
it *will* actually queue at decode (unlike bench9).

At completion, the skill's Step 10 will offer to scale coord D/P
back down — say yes to free GPUs for the sidecar side.

### Run the sidecar side

```
/run-sglang-bench pd-comparison-analysis/bench10_4Dx2GPU_3Px2GPU_multimedia_burst_constrained/sidecar/bench_config
```

Same flow. Both bench_config `benchmark-job.yaml` files are byte-
identical, so the workload is guaranteed to match.

### Analysis after both runs

- Extract per-burst summary metrics from each `sglang-bench-*.log`
  (same awk as used in bench9 SUMMARY).
- Cross-check coord `coordinator.log` `pipeline step timings` for
  per-P-pod balance (should still be roughly even, since prefill
  is not the bottleneck).
- Cross-check sidecar `routing-proxy.log` per-decode-pod request
  counts — this is the one that should show LB imbalance if
  early-bind is the culprit.
- If the fingerprint above materializes (coord wins on TTFT p90+
  at bursts 64/128/256), write the SUMMARY and celebrate.
- If not, follow the "hypothesis dead" path above.

## Files changed vs bench9

- `coord/bench_config/benchmark-job.yaml` — BURST_SIZES, IMAGE_COUNT,
  `--random-image-count` flag added.
- `sidecar/bench_config/benchmark-job.yaml` — identical.
- `coord/bench_config/decode.yaml` — **new file**; deployment manifest
  fetched live with `--max-num-seqs=8` and `--max-num-batched-tokens=4096`
  appended.
- `sidecar/bench_config/decode.yaml` — **new file**; same treatment
  for the sidecar's `pd-disaggregation-nvidia-gpu-vllm-decode`.
- `PLAN.md` — this file.

Nothing else was changed. `prefill.yaml`, EPP ConfigMaps, gateway,
and coordinator settings are all untouched — this experiment
isolates the decode-cap change so any observed delta can be
attributed to it plus the workload variance change.
