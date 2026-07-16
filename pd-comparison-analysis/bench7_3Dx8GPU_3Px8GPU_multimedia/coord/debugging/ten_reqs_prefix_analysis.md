# Bench7 — Ten-Request Prefix-Cache Analysis

Analysis of [ten_reqs_run.pcapng](ten_reqs_run.pcapng) — the network capture of one
sglang `bench_serving` run against the EPD deployment in `dpikus-epd`.

## Capture

- 11 POSTs to `/v1/chat/completions` on `localhost:8080` (1 warmup + 10 bench).
- All carry `model = Qwen/Qwen3-VL-235B-A22B-Instruct`.
- No system prompt. Single user message per request: N image parts
  (`data:image/jpeg;base64,…`) followed by a text part.
- Request params: `stream:true`, `temperature:0.0`, `ignore_eos:true`,
  `max_completion_tokens:22`.

## Assumptions

- **Image tokenization** for 1080p under Qwen3-VL: `patch_size=16`,
  `spatial_merge_size=2` → each 32×32-pixel region = 1 token. 1080p rounded to
  a 32-multiple grid = 60 × 34 = **2,040 tokens per image**.
- **Block size** = 128 tokens (from vLLM `--block-size 128` in the decode/prefill
  deployments).
- **vLLM V1 prefix-cache hashing** includes the multimodal content hash in the
  block containing an image's `<|image_pad|>` tokens. Two requests with different
  image content diverge at the first image's pad tokens even though the token
  IDs are identical.

## Per-request sizes

| Req    | Images | Total tokens | ≈ Blocks |
| ------ | -----: | -----------: | -------: |
| warmup |      3 |        6,235 |       48 |
| req1   |      3 |        6,235 |       48 |
| req2   |      1 |        2,151 |       16 |
| req3   |      1 |        2,208 |       17 |
| req4   |      1 |        2,313 |       18 |
| req5   |      2 |        4,297 |       33 |
| req6   |      3 |        6,452 |       50 |
| req7   |      3 |        6,307 |       49 |
| req8   |      3 |        6,293 |       49 |
| req9   |      3 |        6,273 |       49 |
| req10  |      3 |        6,416 |       50 |

## Common-prefix, two views

### 1. Literal token-ID prefix — upper bound; ignores multimodal content hashing

`<|image_pad|>` has the same token ID regardless of image content, so all
same-image-count pairs share this literal prefix. Reported for reference only:
it is **not** what the vLLM prefix cache uses.

```
          warmup    req1    req2    req3    req4    req5    req6    req7    req8    req9   req10
  warmup    6235    6235    2045    2045    2045    4087    6129    6129    6129    6129    6129
    req1    6235    6235    2045    2045    2045    4087    6129    6129    6129    6129    6129
    req2    2045    2045    2151    2045    2045    2045    2045    2045    2045    2045    2045
    req3    2045    2045    2045    2208    2045    2045    2045    2045    2045    2045    2045
    req4    2045    2045    2045    2045    2313    2045    2045    2045    2045    2045    2045
    req5    4087    4087    2045    2045    2045    4297    4087    4087    4087    4087    4087
    req6    6129    6129    2045    2045    2045    4087    6452    6129    6129    6129    6129
    req7    6129    6129    2045    2045    2045    4087    6129    6307    6129    6129    6129
    req8    6129    6129    2045    2045    2045    4087    6129    6129    6293    6129    6129
    req9    6129    6129    2045    2045    2045    4087    6129    6129    6129    6273    6129
   req10    6129    6129    2045    2045    2045    4087    6129    6129    6129    6129    6416
```

### 2. vLLM prefix-cache common tokens — the one that matters

Both token ID and image content must agree.

```
          warmup    req1    req2    req3    req4    req5    req6    req7    req8    req9   req10
  warmup    6235    6235       4       4       4       4       4       4       4       4       4
    req1    6235    6235       4       4       4       4       4       4       4       4       4
    req2       4       4    2151       4       4       4       4       4       4       4       4
    req3       4       4       4    2208       4       4       4       4       4       4       4
    req4       4       4       4       4    2313       4       4       4       4       4       4
    req5       4       4       4       4       4    4297       4       4       4       4       4
    req6       4       4       4       4       4       4    6452       4       4       4       4
    req7       4       4       4       4       4       4       4    6307       4       4       4
    req8       4       4       4       4       4       4       4       4    6293       4       4
    req9       4       4       4       4       4       4       4       4       4    6273       4
   req10       4       4       4       4       4       4       4       4       4       4    6416
```

### 3. vLLM prefix-cache common blocks — `floor(prefix_tokens / 128)`

```
          warmup    req1    req2    req3    req4    req5    req6    req7    req8    req9   req10
  warmup      48      48       0       0       0       0       0       0       0       0       0
    req1      48      48       0       0       0       0       0       0       0       0       0
    req2       0       0      16       0       0       0       0       0       0       0       0
    req3       0       0       0      17       0       0       0       0       0       0       0
    req4       0       0       0       0      18       0       0       0       0       0       0
    req5       0       0       0       0       0      33       0       0       0       0       0
    req6       0       0       0       0       0       0      50       0       0       0       0
    req7       0       0       0       0       0       0       0      49       0       0       0
    req8       0       0       0       0       0       0       0       0      49       0       0
    req9       0       0       0       0       0       0       0       0       0      49       0
   req10       0       0       0       0       0       0       0       0       0       0      50
```

## Summary — bench requests only (req1..req10; 45 pairs)

- cache-prefix tokens per pair: **min = 4, max = 4, mean = 4.0**
- cache-prefix blocks per pair: **min = 0, max = 0, mean = 0.00**

Only special case:

- **warmup ↔ req1: 6,235 tokens / 48 blocks** — sglang bench replays req1 as its
  warmup, so images and text are byte-identical. This is a harness artifact, not
  workload behavior.

## Bottom line

Across the 10 real bench requests, effective prefix-cache reuse is **zero**.
Every request carries fresh, randomly generated 1080p JPEGs plus a random text
tail — the first image's `<|image_pad|>` block diverges immediately, and the
shared prefix collapses to the 4 tokens
`<|im_start|>user\n<|vision_start|>` that precede the first image.

If this scenario is meant to exercise the prefix cache, the workload has to be
reshaped — reuse images/text across requests, model a repeat-conversation
pattern, or lead with a shared system prompt — otherwise the multimodal cache
is disabled by construction.
