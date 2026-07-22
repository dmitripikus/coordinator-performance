---
name: run-sglang-bench
description: "Run an sglang.bench_serving Job-based benchmark from a bench_config directory (bench8/bench9-style). Handles coord and sidecar sides via one argument — the path to the bench_config folder. Applies the Job, streams its output, saves the sglang-bench-*.log, collects pod logs into the bench side directory, and finally asks whether to scale the vLLM decode/prefill deployments back down."
---

# Run sglang-bench (Job-based) — coord or sidecar

Applies to bench directories under `pd-comparison-analysis/bench*_.../{coord,sidecar}/bench_config/` that contain a `benchmark-job.yaml` running `python -m sglang.bench_serving` as a Kubernetes Job.

**This is NOT the `run_only.sh + config.yaml` (llm-d-benchmark harness) flow.** Do not use this skill for `bench1-*` / `bench6-*` (those use inference-perf via harness); use it for `bench8`, `bench9`, and later bench_config directories whose `benchmark-job.yaml` invokes `sglang.bench_serving`.

## Argument

The skill takes **one positional argument**: the path to the `bench_config` directory (absolute, or relative to the `coordinator-performance` repo root).

- `pd-comparison-analysis/bench9_4Dx2GPU_3Px2GPU_multimedia_burst/coord/bench_config`
- `pd-comparison-analysis/bench9_4Dx2GPU_3Px2GPU_multimedia_burst/sidecar/bench_config`

If the argument is missing, stop and ask which bench and side to run.

Follow the steps in order. If any step fails, stop and report — do not paper over failures.

## Step 1 — Resolve inputs and derive side-specific settings

1. Resolve `BENCH_CONFIG_DIR` to an absolute path. Verify it exists and contains `benchmark-job.yaml`. If not, stop with an error.
2. Compute:
   - `BENCH_SIDE_DIR = dirname(BENCH_CONFIG_DIR)` — this is the `.../coord/` or `.../sidecar/` folder (results and pod_logs land here).
   - `BENCH_ROOT_DIR = dirname(BENCH_SIDE_DIR)` — the `bench*_.../` folder (name encodes topology).
3. Derive `SIDE` from the path: it must contain `/coord/` or `/sidecar/`. If neither, stop with an error.
4. Set namespace + deployment names from `SIDE`:
   - `coord` → `NAMESPACE=dpikus-epd-sglang-bench`, `DECODE_DEPLOY=epd-nvidia-gpu-vllm-decode`, `PREFILL_DEPLOY=epd-nvidia-gpu-vllm-prefill`
   - `sidecar` → `NAMESPACE=dpikus-pd-sglang-bench`, `DECODE_DEPLOY=pd-disaggregation-nvidia-gpu-vllm-decode`, `PREFILL_DEPLOY=pd-disaggregation-nvidia-gpu-vllm-prefill`
5. Parse expected topology from the bench dir name — look for `<N>Dx<G>GPU_<M>Px<G>GPU` in `basename(BENCH_ROOT_DIR)` and capture `EXPECTED_D=N`, `EXPECTED_P=M`. If the pattern is absent, print a warning and skip the topology-count check in Step 3.

Report the resolved values back to the user as a one-liner before continuing.

## Step 2 — Confirm kubectl context

Print `kubectl config current-context` and the target `NAMESPACE`. The user runs across multiple clusters (see `MEMORY.md` — multi-cluster gotcha for bench runs); this is a load-bearing verification step, not paranoia. If the context looks wrong for the namespace, stop and ask the user to switch it.

Then set the namespace on the current context:
```
kubectl config set-context --current --namespace=<NAMESPACE>
```

## Step 3 — Verify topology matches the bench dir name

```
kubectl get deployment <DECODE_DEPLOY> <PREFILL_DEPLOY> -n <NAMESPACE> -o custom-columns=NAME:.metadata.name,REPLICAS:.spec.replicas
```

If `EXPECTED_D`/`EXPECTED_P` were parsed in Step 1:

- If the current replicas match, proceed.
- If they do not match (including if either is 0), **stop and report**. Do not auto-scale — changing topology silently would invalidate the bench name. Ask the user to explicitly confirm scaling before continuing:
  ```
  kubectl scale deployment <DECODE_DEPLOY> -n <NAMESPACE> --replicas=<EXPECTED_D>
  kubectl scale deployment <PREFILL_DEPLOY> -n <NAMESPACE> --replicas=<EXPECTED_P>
  ```

If the topology pattern wasn't parseable, just print current replica counts and continue.

## Step 4 — Wait for all pods to be Running/Ready

```
kubectl wait --for=condition=Ready pod --all -n <NAMESPACE> --timeout=600s
```

vLLM pods can take several minutes to load the model. If the wait times out, run `kubectl get pods -n <NAMESPACE>` and report which pods are not yet Ready — ask the user whether to keep waiting or abort. Do NOT proceed until every pod is Ready — a benchmark that fires before decode is up produces garbage results.

## Step 5 — Delete any prior sglang-bench Job

The Job `metadata.name` in `benchmark-job.yaml` is `sglang-bench` (fixed), so a prior run must be cleared before re-apply:

```
kubectl delete job sglang-bench -n <NAMESPACE> --ignore-not-found
kubectl delete configmap sglang-bench-script -n <NAMESPACE> --ignore-not-found
```

Wait for prior Job pods to disappear:
```
kubectl wait --for=delete pod -l job-name=sglang-bench -n <NAMESPACE> --timeout=120s
```
(The `--for=delete` wait returns immediately if no matching pods exist — that's fine.)

## Step 6 — Apply the benchmark Job

```
kubectl apply -f <BENCH_CONFIG_DIR>/benchmark-job.yaml -n <NAMESPACE>
```

Wait for the Job pod to appear and be Ready (it starts as `PodInitializing` while pulling the sglang image):
```
kubectl wait --for=condition=Ready pod -l job-name=sglang-bench -n <NAMESPACE> --timeout=300s
```

Capture the Job pod name:
```
POD_NAME=$(kubectl get pod -l job-name=sglang-bench -n <NAMESPACE> -o jsonpath='{.items[0].metadata.name}')
```

`POD_NAME` will look like `sglang-bench-xxxxx` — record it, the log file gets named after it.

## Step 7 — Stream the benchmark output to the bench_config directory

Stream and save at the same time so the user sees progress and we have the file on disk:
```
kubectl logs -f <POD_NAME> -n <NAMESPACE> | tee <BENCH_CONFIG_DIR>/<POD_NAME>.log
```

This blocks until the pod's main container exits. If the user interrupts, do not proceed — ask them whether to abort or re-attach.

After `kubectl logs` returns, confirm the Job completed successfully:
```
kubectl get job sglang-bench -n <NAMESPACE> -o jsonpath='{.status.succeeded}'
```
Expected output: `1`. If it's empty or `0`, the Job failed — dump `kubectl describe job sglang-bench -n <NAMESPACE>` and stop.

Quick sanity check on the results file — the last iteration should end with `All rates complete.`:
```
tail -3 <BENCH_CONFIG_DIR>/<POD_NAME>.log
```
If it doesn't, warn the user that the sweep may not have completed all burst sizes.

## Step 8 — Collect pod logs

Use the project-local script (this repo's copy also captures EPP ConfigMaps, which the dev-notebook copy does not):

```
/Users/dpikus/PROJECTS/llm-d/repos/coordinator-performance/k8s/collect_pod_logs.sh <NAMESPACE>
```

The script writes a `pod_logs_<NAMESPACE>_<TIMESTAMP>/` directory in the current working directory. Move it to the bench side folder alongside the log file:

```
mv pod_logs_<NAMESPACE>_* <BENCH_SIDE_DIR>/
```

This matches the layout used by bench8.x — the sglang-bench log lives in `bench_config/`, the pod_logs sit at the `coord/` or `sidecar/` level (one directory up).

## Step 9 — Report completion

Print a short summary:
- Bench root and side (`BENCH_ROOT_DIR`, `SIDE`)
- Namespace and kubectl context that were used
- Job pod name and log file path (`BENCH_CONFIG_DIR/POD_NAME.log`)
- Pod-logs directory path
- Benchmark duration (extract `Benchmark duration (s):` lines from the log if any burst reports them)
- Any warnings encountered (topology drift, incomplete sweep, non-Ready pods, etc.)

## Step 10 — Offer to scale the vLLM deployments back down

The vLLM decode + prefill pods hold GPUs continuously and consume shared cluster capacity even when idle. Ask the user whether to scale them down now (use `AskUserQuestion` — this is a decision only they can make; do NOT auto-scale down):

> "Scale the coord/sidecar vLLM deployments (`<DECODE_DEPLOY>` and `<PREFILL_DEPLOY>`) down to 0 to free the GPUs?"

Present these choices:

- **Yes, scale to 0** — appropriate when the run is standalone or the *other* side (or another bench) needs the GPUs next. Run:
  ```
  kubectl scale deployment <DECODE_DEPLOY> -n <NAMESPACE> --replicas=0
  kubectl scale deployment <PREFILL_DEPLOY> -n <NAMESPACE> --replicas=0
  ```
  Then verify: `kubectl get deployment <DECODE_DEPLOY> <PREFILL_DEPLOY> -n <NAMESPACE>` should show 0 replicas each.

- **No, keep as-is** — appropriate when they'll immediately re-run the same side (e.g., debugging), or when leaving hot pods for a follow-up comparison on the *same* side.

Report the final replica counts either way.

Note: the coord and sidecar sides live in different namespaces with different deployment names, so scaling down one side does NOT free the other side's GPUs. If the user is about to run the counterpart side, ask whether scaling down this side first would help GPU availability on the cluster.

Do NOT commit anything to git as part of this skill — leave that to the user.
