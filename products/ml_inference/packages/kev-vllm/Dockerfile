# The serving image for PostHog's decision models: the official vLLM image plus this package, which registers the model
# classes and the /v1/systemone IO processors through its entry points, plus Caddy for the bearer check and s5cmd to
# fetch the weights. Weights are not in the image; bin/serve.sh fetches them from MODEL_URI into MODEL_DIR.
FROM vllm/vllm-openai:v0.29.0@sha256:c2914767605584b6d8f45686b82de173ecc99e781897aa3d0a66dacd72c51ae1

# vLLM 0.29's V2 model runner does not run the plugin pooling task that IO processors use; the V1 runner does.
# One GPU per box means Gloo only talks to itself, and binding it to loopback avoids resolving the host name, which
# fails at the kernel's 64-character limit in VPCs with a long DHCP domain.
ENV VLLM_USE_V2_MODEL_RUNNER=0 \
    GLOO_SOCKET_IFNAME=lo \
    MODEL_DIR=/models/model \
    MODEL_NAME=jevk5-0.2 \
    PORT=8000

COPY --from=caddy:2.10.2@sha256:c3d7ee5d2b11f9dc54f947f68a734c84e9c9666c92c88a7f30b9cba5da182adb /usr/bin/caddy /usr/local/bin/caddy
ARG S5CMD_VERSION=2.3.0
ARG S5CMD_SHA256=de0fdbfa3aceae55e069ba81a0fc17b2026567637603734a387b2fca06c299b4
RUN curl -sSfL "https://github.com/peak/s5cmd/releases/download/v${S5CMD_VERSION}/s5cmd_${S5CMD_VERSION}_Linux-64bit.tar.gz" -o /tmp/s5cmd.tar.gz \
    && echo "${S5CMD_SHA256}  /tmp/s5cmd.tar.gz" | sha256sum -c - \
    && tar --no-same-owner -xzf /tmp/s5cmd.tar.gz -C /usr/local/bin s5cmd \
    && rm /tmp/s5cmd.tar.gz

WORKDIR /opt/kev-vllm
COPY pyproject.toml ./
COPY kev_vllm ./kev_vllm
# --no-deps keeps the image's torch, transformers and pydantic; the package's own pins are for the export environment.
RUN pip install --no-cache-dir --no-deps . \
    && python3 -c "import kev_vllm.plugin, kev_vllm.checkpoint, kev_vllm.jevk5_io_processor"
COPY bin/serve.sh /usr/local/bin/kev-vllm-serve
COPY serving/Caddyfile /etc/kev-vllm/Caddyfile

# vLLM writes its compile and tokenizer caches under HOME, so the serving user needs one it owns. MODEL_DIR is owned by
# the same user, so a named volume mounted there starts writable and keeps the weights across container restarts.
RUN useradd --system --uid 10001 --create-home --home-dir /home/kev --shell /usr/sbin/nologin kev \
    && install -d -o kev -g kev /models/model
USER kev
ENV HOME=/home/kev

EXPOSE 8000
# vLLM's own health on loopback: Caddy's /health needs the bearer. Start-up covers a weight fetch and graph capture.
HEALTHCHECK --interval=30s --timeout=5s --start-period=900s --retries=3 \
    CMD curl -fs "http://127.0.0.1:${VLLM_PORT:-8001}/health" || exit 1
ENTRYPOINT ["kev-vllm-serve"]
