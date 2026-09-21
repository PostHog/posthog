#!/usr/bin/env bash
# One-shot smoke test on a fresh CUDA box (a Lambda on-demand instance): install the serving environment, fetch an
# exported checkpoint, start vLLM with the Kev plugin, and run the parity comparison against a reference file.
#
#   CHECKPOINT=s3://posthog-ml-training-prod-us-east-1-base-models/posthog/kev-4b-vllm/<version> \
#   REFERENCE=reference-fp32.jsonl bin/gpu-smoke.sh
#
# CHECKPOINT may be an s3:// prefix (needs AWS credentials or presigned access), an http(s) URL to a tarball, or a
# local directory. The script leaves the server running on :8000 and prints the parity summary.
set -euo pipefail

CHECKPOINT=${CHECKPOINT:?s3:// prefix, tarball URL, or local directory with the exported checkpoint}
REFERENCE=${REFERENCE:?parity reference jsonl from 'kev-vllm-parity reference'}
MODEL_NAME=${MODEL_NAME:-kev-4b}
PORT=${PORT:-8000}
MODEL_DIR=${MODEL_DIR:-$HOME/models/$MODEL_NAME}
PACKAGE_DIR=$(cd "$(dirname "$0")/.." && pwd)

command -v nvidia-smi >/dev/null || { echo "no nvidia-smi: not a CUDA box" >&2; exit 1; }
nvidia-smi -L
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

case "$CHECKPOINT" in
  s3://*)
    mkdir -p "$MODEL_DIR"
    command -v aws >/dev/null || uv tool install awscli >/dev/null
    aws s3 sync "$CHECKPOINT" "$MODEL_DIR" --only-show-errors ;;
  http://*|https://*)
    mkdir -p "$MODEL_DIR"
    curl -fsSL "$CHECKPOINT" | tar -xz -C "$MODEL_DIR" ;;
  *)
    MODEL_DIR=$CHECKPOINT ;;
esac
python3 - "$MODEL_DIR" <<'PY'
import hashlib, json, sys
from pathlib import Path
d = Path(sys.argv[1]); manifest = json.loads((d / "manifest.json").read_text())
for name, meta in manifest["files"].items():
    digest = hashlib.sha256(); f = (d / name).open("rb")
    for chunk in iter(lambda: f.read(1 << 20), b""): digest.update(chunk)
    assert digest.hexdigest() == meta["sha256"], f"{name}: checksum mismatch"
print(f"checkpoint ok: {manifest['kev_run']} @ {manifest['kev_hub_revision']}, {len(manifest['files'])} files")
PY

cd "$PACKAGE_DIR"
export UV_PROJECT_ENVIRONMENT="$PACKAGE_DIR/.venv-serve"
# Model Runner V2 (default in vLLM 0.29) does not run the "plugin" pooling task; the V1 runner does.
export VLLM_USE_V2_MODEL_RUNNER=0
uv sync --extra serve
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
