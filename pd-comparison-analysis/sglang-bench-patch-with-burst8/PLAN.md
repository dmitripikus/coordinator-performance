# bench13_burst8_patched_itl — verify the sglang ITL fix

## Purpose

[bench12](../_IGNORE/bench12_burst8_tcpdump/) proved that at burst=8 sidecar,
wire-level SSE cadence is ~12 ms (pcap p50 = 11.85 ms) even though
`sglang.bench_serving` reported ITL p50 = 30.98 ms. The 3× gap was
localized to lines 480–523 of
[bench_serving.py v0.5.14](https://github.com/sgl-project/sglang/blob/v0.5.14/python/sglang/bench_serving.py):
`time.perf_counter()` was being called in the *consumer* coroutine after
the event loop scheduled it, not at the *network* callback where bytes
actually arrived.

bench13 applies a fix that records the arrival timestamp inside
aiohttp's `feed_data()` protocol callback and uses that timestamp when
computing ITL. Same 4D + 3P sidecar setup as bench12, same burst=8, same
tcpdump sidecar to keep an independent wire-level check.

## The patch

The 4-hunk diff in
[sidecar/bench_config/bench_serving_patched.py](sidecar/bench_config/bench_serving_patched.py):

1. `import collections` at the module top.
2. `_install_arrival_tracker(reader)` helper inside
   `async_request_openai_chat_completions`. Wraps `reader.feed_data`
   with a shim that appends `(cumulative_byte_offset, perf_counter)` to
   a deque BEFORE calling the original — so the timestamp fires in the
   protocol callback, not in this coroutine.
3. In the streaming loop, install the tracker, then per `chunk_bytes`
   iteration advance the consumed-byte counter and pop the last
   arrival timestamp whose offset falls within this line's range —
   that's the wire-arrival time for the byte that completed this line.
4. Replace both `time.perf_counter()` calls in the ITL/TTFT branches
   with the popped `wire_ts`.

Diff is at [sidecar/bench_config/bench_serving.patch](sidecar/bench_config/bench_serving.patch)
for readability.

## How the patch reaches the image

The image `docker.io/lmsysorg/sglang:v0.5.14` ships `bench_serving.py`
at `/sgl-workspace/sglang/python/sglang/bench_serving.py`. bench13
ships the patched file as a k8s ConfigMap (`sglang-bench-patched`),
mounts it read-only in the bench container at `/patch`, and the
`run_bench.sh` script's first act is:

```
cp /patch/bench_serving.py /sgl-workspace/sglang/python/sglang/bench_serving.py
```

`run_bench.sh` also (a) `ast.parse`s the patched file BEFORE
overwriting to catch ConfigMap breakage, (b) busts the `.pyc` cache,
and (c) verifies via `import sglang.bench_serving; inspect.getsource(...)`
that the loaded module carries the patch string before invoking
`python -m sglang.bench_serving`.

## Expected result

| metric              | bench12 (unpatched) | bench13 (patched — expected) |
|---|---:|---:|
| pcap wire iarr p50  | 11.85 ms | ~11.85 ms (unchanged, pcap doesn't care) |
| sglang **ITL p50**  | 30.98 ms | **~12 ms** (should now match wire) |
| sglang TPOT p50     | 12.04 ms | ~12.04 ms (unchanged) |
| sglang ITL max      | 645.97 ms | ~645 ms (real first-token gap, unchanged) |

Pass condition: patched ITL p50 within ±10% of wire pcap p50 across all
8 flows.

## Fresh apply steps

1. Create the patched-file ConfigMap:

   ```
   kubectl -n dpikus-pd-sglang-bench create configmap sglang-bench-patched \
     --from-file=bench_serving.py=sidecar/bench_config/bench_serving_patched.py \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

2. Scale up sidecar vLLMs (4D + 3P) and wait ~4 min for readiness.

3. Apply the Job:

   ```
   kubectl -n dpikus-pd-sglang-bench apply -f sidecar/bench_config/benchmark-job.yaml
   ```

4. After job completes (~1.5 min), extract pcap + logs from the pod's
   tcpdump sidecar (which stays alive for 1 h).

5. Scale down.
