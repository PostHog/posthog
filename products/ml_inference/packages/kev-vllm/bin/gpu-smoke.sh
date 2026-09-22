#!/usr/bin/env bash
# One-shot smoke test on a fresh CUDA box (a Lambda on-demand instance): install the serving environment, fetch an
# exported checkpoint, start vLLM with the Kev plugin, and run the parity comparison against a reference file.
#
#   CHECKPOINT=s3://<base-models bucket>/posthog/kev-4b-vllm/<version> bin/gpu-smoke.sh
#
# CHECKPOINT may be an s3:// prefix (needs AWS credentials or presigned access), an http(s) URL to a tarball, or a
# local directory. REFERENCE defaults to the parity fixture published next to the weights. The script leaves the
# server running on :8000 and prints the parity summary.
set -euo pipefail

CHECKPOINT=${CHECKPOINT:?s3:// prefix, tarball URL, or local directory with the exported checkpoint}
MODEL_NAME=${MODEL_NAME:-kev-4b}
PORT=${PORT:-8000}
MODEL_DIR=${MODEL_DIR:-$HOME/models/$MODEL_NAME}
PACKAGE_DIR=$(cd "$(dirname "$0")/.." && pwd)

command -v nvidia-smi >/dev/null || { echo "no nvidia-smi: not a CUDA box" >&2; exit 1; }
nvidia-smi -L
command -v uv >/dev/null || python3 -m pip install --user --quiet uv
export PATH="$HOME/.local/bin:$PATH"

case "$CHECKPOINT" in
  s3://*)
    mkdir -p "$MODEL_DIR"
    command -v aws >/dev/null || uv tool install awscli >/dev/null
    aws s3 sync "$CHECKPOINT" "$MODEL_DIR" --only-show-errors ;;
  https://*)
    mkdir -p "$MODEL_DIR"
    curl -fsSL "$CHECKPOINT" | tar -xz -C "$MODEL_DIR" ;;
  *)
    MODEL_DIR=$CHECKPOINT ;;
esac

cd "$PACKAGE_DIR"
export UV_PROJECT_ENVIRONMENT="$PACKAGE_DIR/.venv-serve"
# Model Runner V2 (default in vLLM 0.29) does not run the "plugin" pooling task; the V1 runner does.
export VLLM_USE_V2_MODEL_RUNNER=0
uv sync --extra serve
uv run kev-vllm-checkpoint verify "$MODEL_DIR"
REFERENCE=${REFERENCE:-$MODEL_DIR/parity/reference-fp32.jsonl}
[ -f "$REFERENCE" ] || { echo "no parity reference at $REFERENCE; pass REFERENCE=" >&2; exit 1; }
nohup uv run --extra serve vllm serve "$MODEL_DIR" --served-model-name "$MODEL_NAME" --port "$PORT" \
  --mamba-ssm-cache-dtype float32 --max-model-len 16384 --gpu-memory-utilization 0.85 > vllm.log 2>&1 &
echo "vllm pid $! (log: $PACKAGE_DIR/vllm.log)"
for _ in $(seq 1 180); do
  curl -fs "localhost:$PORT/health" >/dev/null 2>&1 && break
  sleep 5
done
curl -fs "localhost:$PORT/health" >/dev/null || { tail -50 vllm.log; echo "server did not come up" >&2; exit 1; }
curl -s "localhost:$PORT/pooling" -H 'content-type: application/json' -d "{\"model\": \"$MODEL_NAME\", \"data\": {\"state\": \"It has been two weeks and the refund has not arrived.\", \"questions\": {\"refund\": {\"type\": \"noul\", \"instructions\": \"Is the customer asking about a refund?\"}}}}"
echo
uv run --extra serve kev-vllm-parity compare --base-url "http://localhost:$PORT" --reference "$REFERENCE" --model "$MODEL_NAME"
