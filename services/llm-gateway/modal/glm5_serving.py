"""
GLM-5-FP8 inference on Modal via vLLM.

Adapted from Modal's official vLLM example:
https://github.com/modal-labs/modal-examples/blob/main/06_gpu_and_ml/llm-serving/vllm_inference.py

Deployment (run manually or from CI — Modal handles the infra):
    modal deploy modal/glm5_serving.py                # US (default)
    MODAL_REGION=eu modal deploy modal/glm5_serving.py  # EU

After deploy, Modal prints the endpoint URL. Set it on the LLM Gateway:
    LLM_GATEWAY_GLM5_API_BASE_URL_US=https://<workspace>--posthog-glm5-us-serve.modal.run
    LLM_GATEWAY_GLM5_API_BASE_URL_EU=https://<workspace>--posthog-glm5-eu-serve.modal.run

Prerequisites:
    pip install modal
    modal token set  (or MODAL_TOKEN_ID / MODAL_TOKEN_SECRET env vars)
    Create a Modal secret named "posthog-hf-token" with HF_TOKEN if the model
    requires authentication (GLM-5-FP8 is MIT-licensed, so optional).
"""

import os

import modal

MODEL_ID = "zai-org/GLM-5-FP8"
MODEL_REVISION = "main"
SERVED_MODEL_NAME = "glm-5"
N_GPU = 8
VLLM_PORT = 8000

REGION = os.environ.get("MODAL_REGION", "us")

MODAL_REGIONS = {
    "us": "us-east",
    "eu": "eu-west-1",
}

MINUTES = 60

app = modal.App(f"posthog-glm5-{REGION}")

vllm_image = (
    modal.Image.from_registry("nvidia/cuda:12.8.0-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1", "HF_XET_HIGH_PERFORMANCE": "1"})
    .uv_pip_install(
        "vllm==0.13.0",
        "huggingface-hub[hf_transfer]==0.36.0",
        "hf-xet",
    )
)

hf_cache_vol = modal.Volume.from_name(f"glm5-hf-cache-{REGION}", create_if_missing=True)
vllm_cache_vol = modal.Volume.from_name(f"glm5-vllm-cache-{REGION}", create_if_missing=True)


@app.function(
    image=vllm_image,
    gpu=f"B200:{N_GPU}",
    scaledown_window=5 * MINUTES,
    timeout=10 * MINUTES,
    volumes={
        "/root/.cache/huggingface": hf_cache_vol,
        "/root/.cache/vllm": vllm_cache_vol,
    },
    region=MODAL_REGIONS.get(REGION, "us-east"),
    secrets=[modal.Secret.from_name("posthog-hf-token", required=False)],
)
@modal.concurrent(max_inputs=64)
@modal.web_server(port=VLLM_PORT, startup_timeout=10 * MINUTES)
def serve():
    import subprocess

    cmd = [
        "vllm",
        "serve",
        MODEL_ID,
        "--revision",
        MODEL_REVISION,
        "--served-model-name",
        SERVED_MODEL_NAME,
        "--host",
        "0.0.0.0",
        "--port",
        str(VLLM_PORT),
        "--dtype",
        "auto",
        "--tensor-parallel-size",
        str(N_GPU),
        "--max-model-len",
        "65536",
        "--enable-chunked-prefill",
        "--max-num-seqs",
        "64",
        "--trust-remote-code",
        "--no-enforce-eager",
        "--uvicorn-log-level=info",
    ]

    subprocess.Popen(" ".join(cmd), shell=True)
