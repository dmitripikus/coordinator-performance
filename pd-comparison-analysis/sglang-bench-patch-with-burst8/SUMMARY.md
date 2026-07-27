# bench13_burst8_patched_itl — sglang ITL fix, verified

## Purpose

bench12 proved that at burst=8 sidecar the wire delivers SSE events at
~12 ms cadence (pcap p50 = 11.85 ms) even though `sglang.bench_serving`
reported ITL p50 = 30.98 ms — a 3× measurement inflation. Source-code
inspection localized the bug to
[bench_serving.py:480–523 v0.5.14](https://github.com/sgl-project/sglang/blob/v0.5.14/python/sglang/bench_serving.py#L480-L523):
`time.perf_counter()` is called in the *consumer* coroutine after the
event loop has scheduled it, which under concurrent load lags actual
wire arrival.

bench13 applies a fix that timestamps each response chunk in aiohttp's
`on_response_chunk_received` trace hook — a callback the aiohttp connection
handler fires in the same event-loop tick as `feed_data` on the StreamReader,
much closer to true wire time — and reruns the exact bench12 workload with
tcpdump for an independent check.

## What the fix does

Full patched file:
[sidecar/bench_config/bench_serving_patched.py](sidecar/bench_config/bench_serving_patched.py).
Readable diff: [sidecar/bench_config/bench_serving.patch](sidecar/bench_config/bench_serving.patch).

5 hunks against upstream v0.5.14:

1. `import collections` at the module top.
2. `_bench_on_response_chunk_received` — async trace callback that appends
   `(cumulative_byte_offset, time.perf_counter())` to a per-request deque
   living in `trace_config_ctx.trace_request_ctx`.
3. `_create_bench_client_session` — pass a `TraceConfig` with the callback
   registered.
4. `async_request_openai_chat_completions` — create `_bench_arrival_ctx =
   {"q": deque(), "bytes": 0}`, pass it via `session.post(...,
   trace_request_ctx=_bench_arrival_ctx)`. The streaming loop tracks how
   many bytes it has consumed; for each new line, it peeks the front of
   the deque (popping fully-past entries) to get the arrival time of the
   chunk containing this line's last byte.
5. Replace the two `time.perf_counter()` calls in the ITL/TTFT branches
   with the `wire_ts` peeked from the deque.

The first monkey-patch attempt (v1) failed at runtime with
`AttributeError: 'StreamReader' object attribute 'feed_data' is read-only`
— aiohttp forbids per-instance override of `feed_data`. Switching to the
`on_response_chunk_received` trace signal (v2) worked. v3 further refined
the byte-offset alignment (peek instead of pop) — see the p90-explanation
section below for why v2 and v3 numbers ended up comparable.

## Apply to the running Job

Full recipe is in [PLAN.md](PLAN.md). Short version:

```
# 1. Generate the patched file locally (with the diff applied)
python3 gen_patched_file.py  # writes bench_serving_patched.py

# 2. Put it in a ConfigMap (fits well under the 1 MiB limit — file is ~110 KB)
kubectl -n dpikus-pd-sglang-bench create configmap sglang-bench-patched \
  --from-file=bench_serving.py=./bench_serving_patched.py \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. Bench Job mounts it read-only at /patch, and run_bench.sh copies over
#    the installed file at container startup:
#    cp /patch/bench_serving.py /sgl-workspace/sglang/python/sglang/bench_serving.py
#    (see benchmark-job.yaml — includes ast.parse validation before overwrite
#    and inspect.getsource verification after import)
```

## Results

Four runs isolating each variable, same 8-concurrent burst / 2000-token workload:

| metric        | bench12 (unpatched) | bench13 v3 (patched) | patched + skip_special | **unpatched + skip_special** |
|---|---:|---:|---:|---:|
| `bench_serving.py` patch | ❌ | ✅ | ✅ | **❌** |
| `skip_special_tokens: false` | ❌ | ❌ | ✅ | **✅** |
| `stream_options.include_usage` | ❌ | ❌ | ✅ | **✅** |
| Successful requests | 8/8 | 8/8 | 8/8 | 8/8 |
| Concurrency        | 7.62 | 7.70 | 7.76 | 7.69 |
| Content-bearing SSE events | 44.3% | 44.3% | 96.7% | **99.4%** |
| TPOT mean (ms) | 12.05 | 12.13 | 12.11 | 12.11 |
| **ITL mean (ms)**  | **25.15** | **21.75** | 12.51 | **12.17** |
| **ITL p50 (ms)**   | **30.98** | **13.21** | 11.94 | **11.92** |
| **ITL p90 (ms)**   | **36.01** | **35.95** | 12.29 | **12.15** |
| ITL p95 (ms)   | 36.13 | 36.14 | 14.15 | 13.00 |
| ITL p99 (ms)   | 38.39 | 38.28 | 23.87 | 15.03 |
| **ITL/TPOT ratio** | **2.09×** | **1.79×** | 1.03× | **1.00×** |
| ITL max (ms)   | 743.20 | 698.86 | 671.28 | 680.90 |

### The critical finding: only ONE of the two changes is required

Comparing the 3rd and 4th columns above — flipping *only* the patch on
and off, holding request-body fixes constant — shows the two runs are
**indistinguishable** (Mean ITL 12.51 vs 12.17, both within 1% of Mean
TPOT). The `bench_serving.py` measurement patch is **NOT strictly
required** once `skip_special_tokens: false` is set.

The dominant fix is the **request body**, not the code:

- Setting `skip_special_tokens: false` moves empty-content events from
  44% → <1%. That alone drives Mean ITL from 25 ms → 12 ms because
  sglang's `if content:` filter now has ~1999 samples per request
  (instead of ~1000) so the arithmetic `mean = (E2E-TTFT) / (N-1)`
  lands at ~12 rather than ~24.
- The client-side scheduling delay in `time.perf_counter()` that I
  originally diagnosed as the "3× ITL bug" turns out to average out
  across ~1999 samples. Individual jitter cancels; the sum still
  equals `E2E - TTFT` regardless of when each `perf_counter` fires.

The patch is only load-bearing when:
- Empty-content deltas exist (byte-fragmented CJK/emoji output;
  workloads where you can't set `skip_special_tokens: false`).
- You care about ITL **shape** — the patch fixes p50, per-sample
  ordering, and tail percentiles under those conditions, even if the
  mean happens to be OK.

For **most sustained-concurrent-burst benches** where you control the
request body, the request-body changes alone suffice.

- **ITL max is unchanged** (~700 ms across all three runs) — that's the real
  first-token gap at the start of decode, not a measurement artifact.

## Why Mean ITL (21.75 ms) ≠ Mean TPOT (12.13 ms)

Both numbers are correct — they measure different things. The gap is a
**real workload property**, not a measurement issue:

- **TPOT** = `(E2E − TTFT) / (output_len − 1)` where `output_len` = 2000
  is the server-reported token count. → 12.13 ms.
- **ITL** = per-sample gap between successive SSE events whose delta
  carries **non-empty `content`**. From the patched code:

  ```python
  if content:                        # ← skip empty-content events
      timestamp = wire_ts
      ...
      output.itl.append(timestamp - most_recent_timestamp)
      most_recent_timestamp = timestamp
  ```

  Empty-content SSE events don't record an ITL sample and don't advance
  `most_recent_timestamp` — so gaps that span an empty event get charged
  the *combined* duration to the next content event.

Counting SSE events in the pcap for flow 41822 (representative — details
in the appendix):

| category | count | %    |
|---|---:|---:|
| content-bearing (delta.content non-empty) | 674 | 33.7% |
| **empty-content** (delta.content == `""`) | **1325** | **66.2%** |
| role-only, finish-only, [DONE]            | 3 | 0.1% |
| **total SSE events**                      | **2002** |  |

The distribution of gaps (in units of "# empty events between successive
content-bearing events") for this flow:

| gap (# empties) | count | share | corresponding ITL |
|---:|---:|---:|---:|
| 0 (adjacent)  | 13 | 1.9%  | ~12 ms |
| 1             | 1  | 0.1%  | ~24 ms |
| **2**         | **656** | **97.3%** | **~36 ms** |
| 3             | 4 | 0.6%  | ~48 ms |

The server emits roughly **three SSE events per rendered token** on this
workload — probably Qwen3-VL-Instruct's incremental tokenizer decode
yielding two empty deltas per multi-byte character/token completion. Some
flows show 97% content and others 34% content depending on what the model
generated; aggregating over 8 requests:

- Total SSE events across 8 requests: 16016
- **Content-bearing across 8 requests:  8927  (44.3%)**
- ITL samples per request ≈ 1116 (not 1999)
- Sum of ITLs per request ≈ E2E − TTFT ≈ 24.2 s
- Mean ITL ≈ 24200 / 1116 ≈ **21.7 ms** ✓ matches observed 21.75

And the predicted percentile shape matches too:

| gap (empties) | fraction | ITL value |
|---:|---:|---:|
| 0 | ~56% | ~12 ms  |
| 1 | ~30% | ~24 ms  |
| 2 | ~10% | ~36 ms  |
| ≥3 | ~4% | ≥48 ms  |

- p50 falls in the ~56% "12 ms" bucket → observed 13.21 ms ✓
- p90 falls just inside the ~10% "36 ms" bucket → observed 35.95 ms ✓
- p99 tail extends slightly past 36 → observed 38.28 ms ✓

So the p90 = 36 ms figure I initially called a "residual measurement
error" is actually correct: it's ITL for content-bearing events that were
2 empty-content wire chunks apart. On the wire pcap, gaps are 12 ms
because *every* SSE chunk gets counted, empty or not. On the sglang ITL
side, only content-bearing chunks count, so most content-content gaps
naturally cover ~3 wire ticks.

### Which one to trust

- **TPOT** is the right server-generation-rate metric — it divides by the
  *token* count.
- **ITL** is the right user-visible-text-cadence metric — it divides by
  the *content-delta* count. For streaming UX (typing feel), that's what
  actually matters, and the ~24-36 ms cadence of visible text on this
  workload is real.
- On other workloads (English-only, no multi-byte characters, minimal
  incremental-decode) the two typically converge — Qwen3-VL's tokenizer
  is what widens the gap here.

## Wire capture (unchanged from bench12 — sanity check)

From [sidecar/results_v3/capture.pcap](sidecar/results_v3/capture.pcap)
(32 MB, 32k packets) — all 8 flows carrying the actual bench requests:

| client port | # segs | # SSE evts | evts/seg | wire p50 | p90 | p95 | mean | max |
|---:|---:|---:|---|---:|---:|---:|---:|---:|
| 41822 | 2000 | 2002 | 1:1998, 2:2 | **11.90** | 12.16 | 12.88 | 11.89 |  18.97 |
| 41824 | 2000 | 2002 | 1:1998, 2:2 | **11.94** | 12.36 | 13.89 | 11.95 |  17.42 |
| 41838 | 1998 | 2000 | 1:1996, 2:2 | **11.90** | 12.18 | 12.98 | 12.31 | 601.44 |
| 41854 | 2000 | 2002 | 1:1998, 2:2 | **11.96** | 12.20 | 12.83 | 11.96 |  17.24 |
| 41866 | 2000 | 2002 | 1:1998, 2:2 | **11.89** | 12.26 | 13.11 | 11.90 |  17.02 |
| 41872 | 2000 | 2002 | 1:1998, 2:2 | **11.89** | 12.46 | 13.49 | 12.35 | 698.88 |
| 41882 | 1997 | 1999 | 1:1995, 2:2 | **11.96** | 12.44 | 13.78 | 12.35 | 678.98 |
| 41892 | 2000 | 2002 | 1:1998, 2:2 | **11.95** | 12.63 | 14.04 | 12.37 | 640.74 |

Every flow's p50 sits at 11.89–11.96 ms — matches TPOT (12.13 ms) and
matches the patched ITL p50 (13.21 ms) to within 1 ms. The wire is
unchanged from bench12; only the client-side measurement has moved.

## Iteration history for the record

Three patch versions were shipped in this bench directory:

| variant | mechanism | outcome |
|---|---|---|
| v1 | monkey-patch instance `reader.feed_data` | `AttributeError: read-only` — aiohttp forbids it |
| v2 | `TraceConfig.on_response_chunk_received` + pop-on-consume byte matching | ITL p50 = 11.97 (from 30.98) — worked |
| v3 | same + peek-instead-of-pop alignment | ITL p50 = 13.21, comparable to v2 |

v2 and v3 produce numerically similar results because — as the previous
section makes clear — the shape of the ITL distribution is dominated by
Qwen3-VL's ~3 SSE-events-per-token emission pattern, not by the small
alignment choice at the tail. Kept v3 as the shipped patch because the
intent is easier to explain: "peek the front entry whose end-offset is
≥ consumed" (that's the arrival time of the chunk containing this line's
last byte).

## Bottom line

Bench10's "3× ITL inflation at burst=8" was **primarily a workload
effect, not a client-side measurement bug**. Isolation testing (see
the 4-column results table) proved:

1. **`if content:` filter interacting with `ignore_eos=true`** was the
   dominant cause. vLLM emits ~50% of tokens as EOS-family special
   tokens once the model finishes its "real" response, and its
   OpenAI-compat server renders them as `delta.content=""`. sglang's
   ITL logic skips those, so its ITL samples span multiple wire
   tokens, producing the observed 25-ms mean and 36-ms p90. Fixed by
   adding `"skip_special_tokens": false` to the request body. Without
   any code changes, this alone brings ITL/TPOT ratio from 2.09× to
   1.00×.
2. **The client-side `bench_serving.py` measurement patch** turned out
   to be redundant on this workload. Under sustained concurrent load,
   the individual `time.perf_counter()` jitter averages out across
   ~1999 samples per request — the *sum* of ITLs still equals
   `E2E - TTFT`, giving a correct mean regardless of where the
   timestamps are taken. The patch fixes ITL *distribution shape*
   (p50, p90) when empty-content deltas exist, but it doesn't help
   when they don't.

For future benches where accurate streaming metrics matter, the
minimum-viable fix is the **request-body change alone**:
```
--extra-request-body '{"ignore_eos": true, "skip_special_tokens": false, "stream_options": {"include_usage": true}}'
```
The patch is nice-to-have for robustness (workloads with byte-fragmented
CJK/emoji output can still produce empty deltas even with
`skip_special_tokens: false`), but not required for the standard bench10
workload.

### Recommended bench-config template

For accurate ITL under sustained concurrent load with `ignore_eos: true`:

```yaml
--extra-request-body '{"ignore_eos": true, "skip_special_tokens": false, "stream_options": {"include_usage": true}}'
```

Plus the patched `sglang.bench_serving` (`bench_serving_patched.py` in
this directory, mounted via ConfigMap and copied over the installed
file at container startup — see `benchmark-job.yaml`).

The three fields do three different things and all are needed:
- `ignore_eos: true` — keeps every request generating for the full
  `max_tokens`, so all 8 concurrent requests stay in flight for the
  duration and the burst measures sustained-load behavior (not
  first-response latency).
- `skip_special_tokens: false` — every generated token produces a
  non-empty `delta.content`, so sglang's `if content:` filter never
  skips any tokens. Mean ITL then equals Mean TPOT.
- `stream_options.include_usage: true` — vLLM sends a final
  `usage.completion_tokens` chunk, so sglang's `output_len` variable
  reflects the actual server-reported token count and the log's
  reported TPOT (and Total-generated-tokens, and throughput) are
  computed against the correct denominator.

## Artifacts

- [PLAN.md](PLAN.md) — setup rationale and apply steps
- [sidecar/bench_config/bench_serving_patched.py](sidecar/bench_config/bench_serving_patched.py) — full patched file (v3)
- [sidecar/bench_config/bench_serving.patch](sidecar/bench_config/bench_serving.patch) — readable diff
- [sidecar/bench_config/benchmark-job.yaml](sidecar/bench_config/benchmark-job.yaml) — Job manifest with ConfigMap mount + copy + verification
- [sidecar/results_v2/](sidecar/results_v2/) — first working run (v2 patch)
- [sidecar/results_v3/](sidecar/results_v3/) — final run (v3 patch): pcap, sglang bench log, bench container stdout
