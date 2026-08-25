kubectl scale deploy pd-disaggregation-nvidia-gpu-vllm-prefill --replicas=4

sleep 3
kubectl scale deploy pd-disaggregation-nvidia-gpu-vllm-decode --replicas=6
