#!/usr/bin/env bash
# Container entrypoint: check the checkpoint on disk against its manifest, then serve it with the flags the parity run
# used. Extra arguments go to `vllm serve`.
#
# Binds loopback by default because TLS and the per-instance bearer terminate in a proxy on the same host; set HOST to
# 0.0.0.0 for a bring-up box that is only reachable through a firewall or tunnel.
set -euo pipefail

MODEL_DIR=${MODEL_DIR:-/models/kev-4b}
MODEL_NAME=${MODEL_NAME:-kev-4b}
HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8000}
MAX_MODEL_LEN=${MAX_MODEL_LEN:-16384}
GPU_MEMORY_UTILIZATION=${GPU_MEMORY_UTILIZATION:-0.85}

kev-vllm-checkpoint verify "$MODEL_DIR"
exec vllm serve "$MODEL_DIR" --served-model-name "$MODEL_NAME" --host "$HOST" --port "$PORT" \
  --mamba-ssm-cache-dtype float32 --max-model-len "$MAX_MODEL_LEN" --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" "$@"
