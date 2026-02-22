"""
Modal deployment for GLM-5-FP8 inference via vLLM.

Serves an OpenAI-compatible API endpoint for GLM-5 on Modal GPUs.

Deployment:
    modal deploy glm5_serving.py            # US (default)
    REGION=eu modal deploy glm5_serving.py   # EU

The deployed endpoint URL is used by the LLM Gateway via the
LLM_GATEWAY_GLM5_API_BASE_URL_US / LLM_GATEWAY_GLM5_API_BASE_URL_EU
environment variables.
"""

import os

import modal

MODEL_ID = "zai-org/GLM-5-FP8"
REVISION = "main"
GPU_CONFIG = modal.gpu.B200(count=8)
REGION = os.environ.get("REGION", "us")

app_name = f"posthog-glm5-inference-{REGION}"
app = modal.App(app_name)

vllm_image = (
    modal.Image.from_registry("nvidia/cuda:12.8.0-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1", "HF_XET_HIGH_PERFORMANCE": "1"})
    .uv_pip_install(
        "vllm==0.13.0",
        "huggingface-hub[hf_transfer]==0.36.0",
        "hf-xet",
        "flashinfer-python",
    )
    .run_commands(
        f"huggingface-cli download {MODEL_ID} --revision {REVISION}",
    )
)

hf_cache_vol = modal.Volume.from_name(f"glm5-hf-cache-{REGION}", create_if_missing=True)
vllm_cache_vol = modal.Volume.from_name(f"glm5-vllm-cache-{REGION}", create_if_missing=True)

MINUTES = 60
HOURS = 60 * MINUTES

region_map = {
    "us": "us-east",
    "eu": "eu-west-1",
}


@app.function(
    image=vllm_image,
    gpu=GPU_CONFIG,
    volumes={
        "/root/.cache/huggingface": hf_cache_vol,
        "/root/.cache/vllm": vllm_cache_vol,
    },
    scaledown_window=5 * MINUTES,
    timeout=24 * HOURS,
    allow_concurrent_inputs=128,
    region=region_map.get(REGION, "us-east"),
    secrets=[modal.Secret.from_name("posthog-hf-token", required=False)],
)
@modal.asgi_app()
def serve():
    import vllm.entrypoints.openai.api_server as api_server
    from vllm.engine.arg_utils import AsyncEngineArgs
    from vllm.entrypoints.openai.cli_args import make_arg_parser
    from vllm.utils import FlexibleArgumentParser

    parser = make_arg_parser(FlexibleArgumentParser())
    args = parser.parse_args(
        [
            "--model",
            MODEL_ID,
            "--revision",
            REVISION,
            "--dtype",
            "auto",
            "--max-model-len",
            "65536",
            "--tensor-parallel-size",
            "8",
            "--trust-remote-code",
            "--enable-chunked-prefill",
            "--max-num-seqs",
            "64",
        ]
    )

    engine_args = AsyncEngineArgs.from_cli_args(args)
    engine_args.enable_prefix_caching = True

    server = api_server.build_async_engine_client_and_server(args)
    return server.app
