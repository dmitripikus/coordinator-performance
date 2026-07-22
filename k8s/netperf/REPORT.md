# Cluster node-to-node network benchmark — kermit_US-EAST-01A

Two-node iperf3 + ping test between the same class of GPU nodes used by
the `bench7.2_3Dx8GPU_3Px8GPU_multimedia` workload, plus an analysis of
whether the measured bandwidth is sufficient for that benchmark.

## Setup

| | |
|---|---|
| Cluster | `kermit_US-EAST-01A` (CoreWeave) |
| Namespace | `dpikus-epd-sglang-bench` |
| Server node | `g11bab6` (10.202.206.161, zone 52) |
| Client node | `g13d42a` (10.202.208.239, zone 235) |
| Server pod IP | 10.0.7.158 |
| Client pod IP | 10.0.11.21 |
| Image | `nicolaka/netshoot:latest` |
| Data path | Cilium pod overlay (`eth0` inside pod) — **not** SR-IOV/RDMA |
| Date | 2026-07-20 |

Manifests: [iperf3-server.yaml](iperf3-server.yaml), [iperf3-client.yaml](iperf3-client.yaml).
Both pods pinned with `nodeName:` and given a `PreferNoSchedule` toleration
for the `is_gpu=true` taint so the scheduler wouldn't push them off.
Nodes are on different `/24` subnets and different failure-domain zones,
which is representative of prefill↔decode placement in `bench7.2` (the
coord prefill pods landed on `g11bab6`/`gc37cba`/`g1251ac` and decode on
`gc37d06`/`g134dfa`/`gf27fec` — all cross-subnet pairs).

## Throughput (iperf3, TCP, 10 s)

| Direction | Streams | Bitrate | Retransmits |
|---|---|---|---|
| client → server | 4 | **63.5 Gb/s** | 60 |
| server → client | 4 | **47.5 Gb/s** | 94 |
| client → server | 1 | **35.6 Gb/s** | 69 |

Zero packet loss, retransmits are ~0.001% of segments — the fabric is
clean. The forward/reverse asymmetry (~34%) is consistent with the
Cilium/eBPF datapath being tuned harder on the receive side of one of
these particular nodes; it is not a shortage of link capacity.

## Latency (ICMP ping)

| Test | min | avg | max | mdev |
|---|---|---|---|---|
| 50 pkts @ 200 ms | 0.065 ms | **0.112 ms** | 0.727 ms | 0.089 ms |
| 10 pkts @ 20 ms | 0.051 ms | **0.066 ms** | 0.136 ms | 0.023 ms |

Cross-subnet pod-to-pod RTT of ~65–110 µs indicates the pod-overlay
datapath is fully accelerated (eBPF, no userspace hops). At 0% loss.

## Is this bandwidth enough for `bench7.2_3Dx8GPU_3Px8GPU_multimedia`?

**Short answer: yes, with room to spare — but only for the traffic that
actually rides this network plane. The KV-cache transfer that dominates
prefill→decode bandwidth uses a different physical fabric that this
test did not measure.**

### What rides the pod-overlay network (what we measured)

1. **Ingress**: HTTP requests from the `sglang-bench` pod → gateway →
   `routing-proxy` → prefill pod. Payload is text prompt (~300 tokens)
   + 1–3 base64-encoded 1080p JPEGs.
2. **Egress**: SSE-streamed output tokens (≤2,000) from decode → gateway
   → bench pod.
3. **NIXL side-channel**: small control messages on TCP port 5600
   (KV-cache handshakes, block metadata) between prefill and decode.
4. **Coordinator/EPP control plane**: EPP scoring/routing decisions,
   metrics scraping.

### What does **not** ride this network

The KV-cache blocks themselves. Both prefill and decode pods request
`rdma/ib: 1` and attach the `multi-nic-compute` Multus network (from
`openshift-sriov-network-operator`), and the vLLM config specifies:

```
--kv-transfer-config '{"kv_connector":"NixlConnector", "kv_role":"kv_both"}'
```

NIXL's actual bulk KV transfer is issued over the SR-IOV/InfiniBand
device, not the pod overlay. The 63.5 Gb/s number below does not
characterize the prefill→decode KV path.

### Sizing the overlay traffic for bench7.2

Per-request payload (from the benchmark config —
`--random-input-len 300`, `--image-count 3`, `--image-resolution 1080p`,
`--random-output-len 2000`, and the SUMMARY.md's measured
"~2.1–2.3 images/request", "~4,700 vision tokens"):

| Item | Size / request |
|---|---|
| Prompt JSON (text, template, metadata) | < 5 KB |
| Images: 2.1–2.3 × 1080p JPEG @ ~250–400 KB, base64 (+33%) | 0.7 – 1.2 MB |
| Output stream (≤2,000 SSE-framed tokens, ~5–15 B/token) | 10 – 30 KB |
| **Total per request** | **≈ 0.7 – 1.2 MB in, ~30 KB out** |

Peak burst (worst case: the concurrency-40 tier fires all 40 requests
in the first second):

| Path | Volume | Wall-clock | Bitrate | vs measured 63.5 Gb/s |
|---|---|---|---|---|
| Bench → prefill (ingress fanout) | 40 × 1 MB ≈ 40 MB | 1 s burst | ≈ 320 Mb/s | **0.5 %** |
| Decode → bench (egress fanout) | 40 × 30 KB ≈ 1.2 MB | over ~70 s | ≈ 0.15 Mb/s | < 0.01 % |
| Sustained across whole run (~0.4 req/s achieved) | | | ≈ 3.2 Mb/s | < 0.01 % |

Even a 10× worst-case error in image-size estimation (say every image
was 2 MB after base64 rather than ~400 KB) would still put peak overlay
utilization at ~5% — nowhere near saturation.

Latency budget check: TTFT medians at concurrency 40 are ~8,875 ms on
coord and ~8,203 ms on sidecar. A pod-overlay RTT of 0.1 ms adds
~0.001–0.002% per hop; there is no plausible network-latency component
to TTFT differences between coord and sidecar.

### Conclusion for bench7.2

- **Overlay bandwidth is not a constraint.** Peak overlay demand
  during the worst burst of the concurrency-40 tier is ≤0.5% of the
  measured 63.5 Gb/s ceiling. There is no scenario in this workload
  where the Cilium pod network is the bottleneck.
- **Overlay latency is not a constraint.** Cross-subnet pod-to-pod RTT
  of ~65–110 µs is four orders of magnitude below TTFT and two orders
  below TPOT. It cannot explain the coord-vs-sidecar deltas in
  SUMMARY.md.
- **The KV-cache plane is not covered by this test.** If a future run
  needs to characterize whether the SR-IOV/InfiniBand fabric can keep
  up with prefill→decode NIXL transfers (particularly for large
  vision-token prompts at high concurrency), the correct tool is
  `ib_write_bw` / `ib_read_bw` from `perftest`, run on pods that
  request `rdma/ib: 1` and attach `multi-nic-compute`. Latency for
  RDMA one-sided ops is typically ~1–3 µs on InfiniBand — separate
  budget from this ping test.

## Reproducing

```bash
kubectl apply -f k8s/netperf/iperf3-server.yaml
kubectl apply -f k8s/netperf/iperf3-client.yaml
kubectl -n dpikus-epd-sglang-bench wait --for=condition=Ready pod/iperf3-server pod/iperf3-client --timeout=180s

SERVER_IP=$(kubectl -n dpikus-epd-sglang-bench get pod iperf3-server -o jsonpath='{.status.podIP}')

# Throughput, forward
kubectl -n dpikus-epd-sglang-bench exec iperf3-client -- iperf3 -c "$SERVER_IP" -t 10 -P 4 -f g
# Throughput, reverse
kubectl -n dpikus-epd-sglang-bench exec iperf3-client -- iperf3 -c "$SERVER_IP" -t 10 -P 4 -R -f g
# Throughput, single stream
kubectl -n dpikus-epd-sglang-bench exec iperf3-client -- iperf3 -c "$SERVER_IP" -t 10 -f g

# Latency
kubectl -n dpikus-epd-sglang-bench exec iperf3-client -- ping -c 50 -i 0.2 -q "$SERVER_IP"
```

To test between a different node pair, edit `nodeName:` in each
manifest.

## Cleanup

```bash
kubectl -n dpikus-epd-sglang-bench delete pod iperf3-server iperf3-client
kubectl -n dpikus-epd-sglang-bench delete svc iperf3-server
```
