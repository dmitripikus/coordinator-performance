# bench11_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer — PLAN

Follow-up to `bench10_4Dx2GPU_3Px2GPU_multimedia_burst_constrained`, which
was itself a follow-up to `bench9_4Dx2GPU_3Px2GPU_multimedia_burst`.

## Recap: why bench9 and bench10 both produced null results

- **Sanity check confirmed**: both sides run identical scoring configuration
  — the schedulingProfile actually loaded by the EPP references ONLY
  `active-request-scorer`. `kv-cache-utilization-scorer` and `queue-scorer`
  are declared in the plugins list of both ConfigMaps but never wired into
  the profile that scores endpoints.
- `active-request-scorer` is EPP-side bookkeeping. It reflects every
  assignment the EPP has made, including the ones just made moments before
  in the same burst. So sidecar's arrival-time bind sees a correct spread
  of prior burst-mates, coord's post-prefill bind sees the same correct
  spread — they compute the same output and land the same distribution.
- **The premise "sidecar's arrival-time state is stale" was false** for
  this scorer. That's what killed the hypothesis in bench9 and bench10.

## bench11 fixes both root causes

### Change 1 — multi-scorer profile (both sides, symmetric)

Rewire the scoring profile so scoring actually reads live vLLM `/metrics`
state, not just an EPP-internal counter:

```yaml
schedulingProfiles:
- name: decode        # (or "default" for coord's epd-plugins.yaml)
  plugins:
  - pluginRef: decode-filter                    # (sidecar only — coord doesn't have a P/D filter step here)
  - pluginRef: kv-cache-utilization-scorer
    weight: 3
  - pluginRef: queue-scorer
    weight: 2
  - pluginRef: active-request-scorer
    weight: 1
  - pluginRef: max-score-picker                 # (sidecar; coord uses implicit default picker)
```

Both `kv-cache-utilization-scorer` and `queue-scorer` read from the
metrics-data-source plugin (also added explicitly to both ConfigMaps —
it was only declared in `default-plugins.yaml` before, not in the
profiles actually loaded). Their values evolve on the metrics-scrape
cadence (typically seconds), so they can differ between arrival-time
and prefill-completion-time.

Applied symmetrically to both sides — this makes scorer choice a
controlled variable and isolates the timing effect.

### Change 2 — asymmetric D-pool (Option A from proposal)

Split the 4 decode pods into two Deployments with different capacity:

- `epd-nvidia-gpu-vllm-decode` (coord) / `pd-disaggregation-nvidia-gpu-vllm-decode` (sidecar)
  → renamed conceptually to **"fast"** — 2 replicas, `--max-num-seqs=8`
- `*-decode-slow` (new Deployment on each side)
  → **"slow"** — 2 replicas, `--max-num-seqs=4`

Both Deployments share the labels required by the InferencePool selector
(`llm-d.ai/guide=epd` + `llm-d.ai/role=decode` on coord; `llm-d.ai/guide=pd-disaggregation`
on sidecar), so they contribute to the same pool.

Additional distinguishing label `llm-d.ai/variant=fast|slow` on both
`.spec.selector.matchLabels` and `.spec.template.metadata.labels` so
each Deployment only owns its own pods.

Total decode capacity: 2 × 8 + 2 × 4 = 24 slots (vs bench10's 32).
Bursts still stress the fleet at the same relative points (see below).

**Why this exposes deferred-decode's advantage**: `active-request-scorer`
counts requests equally regardless of which pod they hit, so it will
spread the burst evenly (~25% to each of the 4 pods). But the 4-seq
pods reach saturation on their 5th request while the 8-seq pods still
have slack. `kv-cache-utilization-scorer` and `queue-scorer` see this
imbalance in the vLLM metrics — the 4-seq pods build KV pressure and
queue depth faster. With Change 1's multi-scorer profile, that live
metric wins the score comparison, and requests get steered to the 8-seq
pods.

Timing matters here: at arrival, all 4 pods look empty to metrics.
By prefill-completion (2-5s later on a multi-image request), the
metrics have picked up the load asymmetry — precisely the substrate
coord's deferred-bind needs.

## Files

```
bench11_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer/
├── PLAN.md                                             (this file)
├── coord/
│   └── bench_config/
│       ├── benchmark-job.yaml                           (unchanged from bench10)
│       ├── coordinator-epd-decode-epp-cm.yaml           (NEW — Change 1: patched EPP ConfigMap)
│       ├── coordinator-epd-prefill-epp-cm.yaml          (fetched but NOT modified — prefill scoring unchanged)
│       ├── decode-fast.yaml                             (was decode.yaml, now replicas=2 + variant=fast label)
│       └── decode-slow.yaml                             (NEW — Change 2: max-num-seqs=4, replicas=2, variant=slow)
└── sidecar/
    └── bench_config/
        ├── benchmark-job.yaml                           (unchanged from bench10)
        ├── pd-disaggregation-epp-cm.yaml                (NEW — Change 1: patched EPP ConfigMap)
        ├── decode-fast.yaml                             (was decode.yaml, replicas=2 + variant=fast label)
        └── decode-slow.yaml                             (NEW — Change 2: max-num-seqs=4, replicas=2, variant=slow)
```

## Setup steps (in order)

Both sides currently scaled to 0 replicas (bench10 tore them down).
Nothing in production is affected by these Deployment/ConfigMap changes.

### 1. Apply Change 1 — EPP ConfigMaps + roll the EPP pods

```bash
# Coord decode-EPP config
kubectl apply -f coord/bench_config/coordinator-epd-decode-epp-cm.yaml
kubectl rollout restart deployment/coordinator-epd-decode-epp -n dpikus-epd-sglang-bench
kubectl rollout status deployment/coordinator-epd-decode-epp -n dpikus-epd-sglang-bench --timeout=120s

# Sidecar EPP config
kubectl apply -f sidecar/bench_config/pd-disaggregation-epp-cm.yaml
kubectl rollout restart deployment/pd-disaggregation-epp -n dpikus-pd-sglang-bench
kubectl rollout status deployment/pd-disaggregation-epp -n dpikus-pd-sglang-bench --timeout=120s
```

Restart is required because the EPP loads and caches its config file at
startup — a ConfigMap change alone won't take effect on a running pod.

### 2. Apply Change 2 — replace decode Deployments with fast+slow

The existing decode Deployment's `.spec.selector.matchLabels` is
IMMUTABLE, so it must be deleted and re-created with the new selector
(one that includes `variant=fast`). Both sides:

```bash
# Coord: delete existing decode, apply fast+slow
kubectl delete deployment epd-nvidia-gpu-vllm-decode -n dpikus-epd-sglang-bench --ignore-not-found
kubectl apply -f coord/bench_config/decode-fast.yaml
kubectl apply -f coord/bench_config/decode-slow.yaml

# Sidecar: same
kubectl delete deployment pd-disaggregation-nvidia-gpu-vllm-decode -n dpikus-pd-sglang-bench --ignore-not-found
kubectl apply -f sidecar/bench_config/decode-fast.yaml
kubectl apply -f sidecar/bench_config/decode-slow.yaml
```

At this point, replicas are still at 0 on all four Deployments —
the skill's Step 3 will prompt to scale them up.

### 3. Verify the InferencePool sees 4 pods, not 2, when scaled

Quick sanity check (do this AFTER the skill scales up the deployments,
before it applies the Job):

```bash
# Coord side: should list 4 pods (2 fast + 2 slow)
kubectl get pods -n dpikus-epd-sglang-bench -l "llm-d.ai/guide=epd,llm-d.ai/role=decode" \
  -o custom-columns=NAME:.metadata.name,VARIANT:.metadata.labels.llm-d\\.ai/variant,STATUS:.status.phase

# Sidecar side: same
kubectl get pods -n dpikus-pd-sglang-bench -l "llm-d.ai/guide=pd-disaggregation,llm-d.ai/role=decode" \
  -o custom-columns=NAME:.metadata.name,VARIANT:.metadata.labels.llm-d\\.ai/variant,STATUS:.status.phase
```

Expect exactly 2 with `variant=fast` and 2 with `variant=slow` per side.

### 4. Run the bench (both sides, back-to-back)

```
/run-sglang-bench pd-comparison-analysis/bench11_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer/coord/bench_config
# then (after coord scale-down):
/run-sglang-bench pd-comparison-analysis/bench11_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer/sidecar/bench_config
```

Skill's Step 3 will detect 0/0 on decode+prefill and prompt scaling to
4/3 (fast Deployment scales to 2, slow to 2 — total 4 → matches
`EXPECTED_D=4` from the dir name pattern `2Dfast_2Dslow`). Actually,
the dir name has `2Dfast_2Dslow` which won't match the `\d+Dx\d+GPU`
regex the skill uses — the topology check will just print a warning
and continue.

## Expected fingerprint

Same burst sweep as bench10 (`BURST_SIZES=(8 16 32 64 128 256)`,
random-image-count 1–5, 300-in / 2000-out), so results are directly
comparable to bench10's numbers.

Total fleet slots: 2×8 + 2×4 = **24** (vs bench10's 32).

| burst | vs cliff (24) | expected regime | prediction |
|---:|---|---|---|
| 8   | 0.33× | under, no queue | both sides equal (control) |
| 16  | 0.67× | still under | both roughly equal |
| 32  | 1.33× | over 4-seq pods' capacity but 8-seq pods still have slack | **first place coord should lead** — sidecar's arrival-time bind spreads evenly, wasting requests on already-saturated slow pods; coord's post-prefill bind steers to fast pods |
| 64  | 2.67× | deep queue on slow pods | coord's advantage widens |
| 128 | 5.3× | all pods overloaded | still coord-favorable; gap may narrow as fast pods also saturate |
| 256 | 10.7× | fully overloaded | mostly workload-dominated; small residual coord advantage |

**What "coord wins" looks like in numbers**:

- **TTFT p50 at burst 32-128**: coord noticeably lower (maybe 20-50% lower).
- **TTFT p90/p99 at burst 32-64**: coord *substantially* lower — sidecar's
  "unlucky" requests that got early-bound to a slow pod eat a full
  ~30s decode wait; coord's late-bind avoids them.
- **Duration at burst 32-128**: coord shorter.
- **Throughput ratio**: coord ahead by 15-30% at burst 32-64.
- **TPOT**: identical between sides at every burst (decode speed is
  per-pod, unaffected by which pod ran it).
- **Per-pod request count** (from vLLM metrics or sidecar `routing-proxy.log`):
  sidecar should show ~equal split fast/slow (~25% each of 4 pods);
  coord should show fast pods handling 60-80% of requests, slow pods 20-40%.

**What "hypothesis fully dead" looks like even with Change 1+2**:

- If numbers are still within ±5% between coord and sidecar at bursts
  32–128 with these changes in effect, the deferred-bind mechanism
  fundamentally cannot beat early-bind at the seconds timescale of
  metrics evolution in this vLLM+EPP+Nixl stack. Further experiments
  would need to target the timescale mismatch itself (either much
  slower prefill or much faster metrics refresh).

## Rollback

To undo bench11 and return to a bench10-like uniform 4×8 fleet:

```bash
# Delete the new decode Deployments (both sides)
kubectl delete deployment epd-nvidia-gpu-vllm-decode epd-nvidia-gpu-vllm-decode-slow -n dpikus-epd-sglang-bench
kubectl delete deployment pd-disaggregation-nvidia-gpu-vllm-decode pd-disaggregation-nvidia-gpu-vllm-decode-slow -n dpikus-pd-sglang-bench

# Re-apply the bench10 unified decode.yaml
kubectl apply -f ../bench10_4Dx2GPU_3Px2GPU_multimedia_burst_constrained/coord/bench_config/decode.yaml
kubectl apply -f ../bench10_4Dx2GPU_3Px2GPU_multimedia_burst_constrained/sidecar/bench_config/decode.yaml

# Re-apply bench10 EPP ConfigMaps (they'll revert the profile change too)
# — actually, easier: fetch fresh from a bench9 or bench10 pod_logs archive if a rollback is needed.
```

## Files changed vs bench10

- Renamed: `decode.yaml` → `decode-fast.yaml` (both sides; replicas 4 → 2, added `variant=fast` label)
- Added: `decode-slow.yaml` (both sides; replicas 2, max-num-seqs 4, `variant=slow`)
- Added: `coordinator-epd-decode-epp-cm.yaml` (coord — patched EPP config)
- Added: `pd-disaggregation-epp-cm.yaml` (sidecar — patched EPP config)
- Added: `coordinator-epd-prefill-epp-cm.yaml` (coord — fetched for reference only, unchanged)
- `benchmark-job.yaml` on both sides is byte-identical to bench10 — same workload for direct comparison.
