#!/usr/bin/env bash
# Container entrypoint and the whole serving box: fetch the checkpoint when MODEL_DIR does not already match its
# manifest, run vLLM on loopback, and put Caddy in front of it on PORT. Caddy rejects a request without the bearer and
# exposes only the decision endpoint, health and metrics. The container exits when either process does, so the host's
# restart policy brings both back. Extra arguments go to `vllm serve`.
set -euo pipefail

MODEL_DIR=${MODEL_DIR:-/models/model}
MODEL_URI=${MODEL_URI:-}
MODEL_NAME=${MODEL_NAME:-jevk5-0.2}
DTYPE=${DTYPE:-auto}
MAX_MODEL_LEN=${MAX_MODEL_LEN:-16384}
GPU_MEMORY_UTILIZATION=${GPU_MEMORY_UTILIZATION:-0.85}
MAX_NUM_QUEUED_TOKENS=${MAX_NUM_QUEUED_TOKENS:-}
export PORT=${PORT:-8000} VLLM_PORT=${VLLM_PORT:-8001} AWS_REGION=${AWS_REGION:-us-east-1}
: "${DECISION_BEARER:?set DECISION_BEARER to the bearer the AI gateway sends}"
export DECISION_BEARER

# About four seconds of the GPU's measured prefill (README, "Load test on an L4"), so an overloaded box answers 503
# well inside the gateway's wait. A GPU nobody has measured gets no guess, because a queue longer than the wait turns
# overload into timeouts.
if [ -z "$MAX_NUM_QUEUED_TOKENS" ]; then
  gpu=$(python3 -c 'import torch; print(torch.cuda.get_device_name(0))' 2>/dev/null || true)
  case "$gpu" in
    *L4*) MAX_NUM_QUEUED_TOKENS=24000 ;;
    *T4*) MAX_NUM_QUEUED_TOKENS=5000 ;;
    *)
      echo "no measured queue limit for GPU '${gpu:-unknown}': set MAX_NUM_QUEUED_TOKENS to about four seconds of its prefill tokens" >&2
      exit 1
      ;;
  esac
fi

if ! kev-vllm-checkpoint verify "$MODEL_DIR" >/dev/null 2>&1; then
  if [ -z "$MODEL_URI" ]; then
    echo "no checkpoint matching its manifest at $MODEL_DIR, and no MODEL_URI to fetch one from" >&2
    exit 1
  fi
  echo "fetching $MODEL_URI into $MODEL_DIR" >&2
  s5cmd --log error cp "${MODEL_URI%/}/*" "$MODEL_DIR/"
fi
kev-vllm-checkpoint verify "$MODEL_DIR"

# Bash as PID 1 does not pass `docker stop` on to its children.
trap 'kill $(jobs -p) 2>/dev/null' TERM INT
vllm serve "$MODEL_DIR" --served-model-name "$MODEL_NAME" --host 127.0.0.1 --port "$VLLM_PORT" --dtype "$DTYPE" \
  --mamba-ssm-cache-dtype float32 --max-model-len "$MAX_MODEL_LEN" --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
  --max-num-queued-tokens "$MAX_NUM_QUEUED_TOKENS" "$@" &
caddy run --config /etc/kev-vllm/Caddyfile --adapter caddyfile &

status=0
wait -n || status=$?
kill $(jobs -p) 2>/dev/null || true
wait || true
exit "$status"
