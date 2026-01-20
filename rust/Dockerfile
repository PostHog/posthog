# Taken from: https://depot.dev/docs/container-builds/how-to-guides/optimal-dockerfiles/rust-dockerfile
FROM rust:1.91-bookworm AS base
# Note - sccache pinned due to problem with depot builds. See https://posthog.slack.com/archives/C0457KENW2E/p1768558484810999?thread_ts=1768497407.301109&cid=C0457KENW2E
RUN cargo install --locked cargo-chef sccache@0.12.0
ENV RUSTC_WRAPPER=sccache SCCACHE_DIR=/sccache

FROM base AS planner
WORKDIR /app
ARG BIN

COPY . .
RUN cargo chef prepare --recipe-path recipe.json --bin $BIN

FROM base AS builder
WORKDIR /app
ARG BIN

# Ensure working C compile setup (not installed by default in arm64 images)
# libclang-dev is required for bindgen (used by librocksdb-sys)
# pkg-config is required for openssl-sys to find system OpenSSL
RUN apt-get update && apt-get install build-essential libssl-dev pkg-config cmake libclang-dev -y

COPY --from=planner /app/recipe.json recipe.json
RUN --mount=type=cache,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,target=/usr/local/cargo/git,sharing=locked \
    --mount=type=cache,target=$SCCACHE_DIR,sharing=locked \
    cargo chef cook --release --recipe-path recipe.json --bin $BIN

COPY . .
RUN --mount=type=secret,id=SCCACHE_WEBDAV_ENDPOINT,required=false \
    --mount=type=secret,id=SCCACHE_WEBDAV_TOKEN,required=false \
    --mount=type=cache,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,target=/usr/local/cargo/git,sharing=locked \
    --mount=type=cache,target=$SCCACHE_DIR,sharing=locked \
    if [ -f "/run/secrets/SCCACHE_WEBDAV_ENDPOINT" ] && [ -f "/run/secrets/SCCACHE_WEBDAV_TOKEN" ]; then \
    SCCACHE_WEBDAV_ENDPOINT=$(cat /run/secrets/SCCACHE_WEBDAV_ENDPOINT) \
    SCCACHE_WEBDAV_TOKEN=$(cat /run/secrets/SCCACHE_WEBDAV_TOKEN) \
    cargo build --release --bin $BIN; \
    else \
    cargo build --release --bin $BIN; \
    fi


FROM debian:bookworm-slim AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libssl-dev "ca-certificates" \
    "curl" \
    "brotli" \
    && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir share && \
    ( curl -s -L "https://mmdbcdn.posthog.net/" --http1.1 | brotli --decompress --output=./share/GeoLite2-City.mmdb ) && \
    chmod -R 755 ./share/GeoLite2-City.mmdb && \
    mkdir -p /app/share && \
    mv ./share/GeoLite2-City.mmdb /app/share/ && \
    rm -rf ./share

ARG BIN
ENV BIN=$BIN
WORKDIR /app

USER nobody

COPY --from=builder /app/target/release/$BIN /usr/local/bin
ENTRYPOINT ["/bin/sh", "-c", "/usr/local/bin/$BIN"]
