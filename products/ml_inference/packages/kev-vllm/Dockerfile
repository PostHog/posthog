# The serving image for Kev decision models: the official vLLM image plus this package, which registers the model class
# and the /v1/systemone IO processor through its entry points. Weights are not in the image; mount an exported
# checkpoint at MODEL_DIR (see bin/serve.sh).
FROM vllm/vllm-openai:v0.29.0@sha256:c2914767605584b6d8f45686b82de173ecc99e781897aa3d0a66dacd72c51ae1

# vLLM 0.29's V2 model runner does not run the plugin pooling task that IO processors use; the V1 runner does.
ENV VLLM_USE_V2_MODEL_RUNNER=0 \
    MODEL_DIR=/models/kev-4b \
    MODEL_NAME=kev-4b \
    PORT=8000

WORKDIR /opt/kev-vllm
COPY pyproject.toml ./
COPY kev_vllm ./kev_vllm
# --no-deps keeps the image's torch, transformers and pydantic; the package's own pins are for the export environment.
RUN pip install --no-cache-dir --no-deps . \
    && python3 -c "import kev_vllm.plugin, kev_vllm.checkpoint"
COPY bin/serve.sh /usr/local/bin/kev-vllm-serve

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD curl -fs "http://127.0.0.1:${PORT}/health" || exit 1
ENTRYPOINT ["kev-vllm-serve"]
