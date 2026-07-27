podman run --rm -it \
  -e HF_TOKEN="$HF_TOKEN" \
  -v ~/.cache/sglang:/root/.cache \
  docker.io/lmsysorg/sglang:v0.5.14 \
  python -m sglang.bench_serving \
    --random-image-count \
    --model Qwen/Qwen3-VL-235B-A22B-Instruct \
    --num-prompts 10 \
    --dataset-name image \
    --random-input-len 300 \
    --random-output-len 200 \
    --image-count 3 \
    --image-resolution 1080p \
    --host host.containers.internal \
    --port 8080 \
    --backend sglang-oai-chat \
    --request-rate 10 \
    --ready-check-timeout-sec 0    


