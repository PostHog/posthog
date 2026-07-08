# Taken from: https://depot.dev/docs/container-builds/how-to-guides/optimal-dockerfiles/rust-dockerfile
FROM rust:1.91-bookworm AS base
# Note - sccache pinned due to problem with depot builds. See https://posthog.slack.com/archives/C0457KENW2E/p1768558484810999?thread_ts=1768497407.301109&cid=C0457KENW2E
RUN cargo install --locked cargo-chef sccache@0.12.0
ENV RUSTC_WRAPPER=sccache SCCACHE_LOG=debug SCCACHE_DIR=/sccache

FROM base AS planner
WORKDIR /app
ARG BIN
ARG BUILD_FEATURES=""
ENV PROTO_ROOT=../proto

COPY . .
RUN cargo chef prepare --recipe-path recipe.json --bin $BIN

FROM base AS builder
WORKDIR /app
ARG BIN
ARG BUILD_FEATURES=""
ARG SCCACHE_WEBDAV_KEY_PREFIX
# Extra compiler flags for specific images, set per-image in
# .github/rust-images.yml. Cymbal opts into frame pointers and unwind tables so
# the profiler can walk Rust and native dependency stacks on aarch64.
# Guarded RUSTFLAGS exports below because the RUSTFLAGS env var replaces
# [build].rustflags from .cargo/config.toml entirely (no merging): when extra
# flags are set the export re-adds --cfg tokio_unstable, and when unset
# RUSTFLAGS stays unset so .cargo/config.toml keeps applying.
ARG EXTRA_RUSTFLAGS=""
ARG EXTRA_CFLAGS=""
ENV PROTO_ROOT=../proto SCCACHE_WEBDAV_KEY_PREFIX=${SCCACHE_WEBDAV_KEY_PREFIX}

# Ensure working C compile setup (not installed by default in arm64 images)
# libclang-dev is required for bindgen (used by librocksdb-sys)
# pkg-config is required for openssl-sys to find system OpenSSL
RUN apt-get update && apt-get install build-essential libssl-dev pkg-config cmake libclang-dev protobuf-compiler -y

COPY --from=planner /app/recipe.json recipe.json
RUN --mount=type=cache,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,target=/usr/local/cargo/git,sharing=locked \
    --mount=type=cache,target=$SCCACHE_DIR,sharing=locked \
    SCCACHE_NO_DAEMON=1 SCCACHE_START_SERVER=1 sccache 2>&1 & \
    if [ -n "$EXTRA_RUSTFLAGS" ]; then export RUSTFLAGS="--cfg tokio_unstable $EXTRA_RUSTFLAGS"; fi && \
    if [ -n "$EXTRA_CFLAGS" ]; then export CFLAGS="$EXTRA_CFLAGS" CXXFLAGS="$EXTRA_CFLAGS" AWS_LC_SYS_CFLAGS="$EXTRA_CFLAGS"; fi && \
    cargo chef cook --release --recipe-path recipe.json --bin $BIN ${BUILD_FEATURES:+--features $BUILD_FEATURES} && \
    sccache --show-stats

COPY . .
RUN --mount=type=secret,id=SCCACHE_WEBDAV_ENDPOINT,required=false \
    --mount=type=secret,id=SCCACHE_WEBDAV_TOKEN,required=false \
    --mount=type=cache,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,target=/usr/local/cargo/git,sharing=locked \
    --mount=type=cache,target=$SCCACHE_DIR,sharing=locked \
    if [ -f "/run/secrets/SCCACHE_WEBDAV_ENDPOINT" ] && [ -f "/run/secrets/SCCACHE_WEBDAV_TOKEN" ]; then \
        export SCCACHE_WEBDAV_ENDPOINT=$(cat /run/secrets/SCCACHE_WEBDAV_ENDPOINT); \
        export SCCACHE_WEBDAV_TOKEN=$(cat /run/secrets/SCCACHE_WEBDAV_TOKEN); \
    fi && \
    SCCACHE_NO_DAEMON=1 SCCACHE_START_SERVER=1 sccache 2>&1 & \
    if [ -n "$EXTRA_RUSTFLAGS" ]; then export RUSTFLAGS="--cfg tokio_unstable $EXTRA_RUSTFLAGS"; fi && \
    if [ -n "$EXTRA_CFLAGS" ]; then export CFLAGS="$EXTRA_CFLAGS" CXXFLAGS="$EXTRA_CFLAGS" AWS_LC_SYS_CFLAGS="$EXTRA_CFLAGS"; fi && \
    cargo build --release --bin $BIN ${BUILD_FEATURES:+--features $BUILD_FEATURES} && \
    sccache --show-stats

# Upload native debug symbols (with source context) to PostHog error tracking,
# so panics and exceptions captured by common-posthog symbolicate server-side.
# They go to the internal PostHog project (POSTHOG_CLI_ENV_ID=2 on US cloud),
# the same project the frontend sourcemap upload in the root Dockerfile targets.
# Runs only when CI mounts the upload token (master builds on the canonical
# deploy repo — see _rust-build-images.yml); PR and local builds skip it.
# Upload failures warn instead of failing the build: symbols must never block
# shipping an image. The cargo registry cache mounts make dependency sources
# visible to --include-source at the paths DWARF records for them.
# No release stamping: symbolication resolves by GNU build id alone, and the
# amd64/arm64 builds run concurrently — the CLI's lookup-then-create release
# flow would race and drop one platform's upload.
#
# SYMBOL_UPLOAD_TRIGGER exists because secret mounts are not part of the layer
# cache key: without it, a PR build's skipped-upload layer could be reused by a
# master build and silently skip the upload. CI sets it to the unique run id
# when the token is provided, so token-bearing builds always re-execute this
# layer; token-less builds keep a constant empty value and stay cached.
#
# The CLI installer is pinned to an immutable release tag and checksum-verified
# before execution. To upgrade, change POSTHOG_CLI_VERSION and recompute:
#   curl -LsSf "https://github.com/PostHog/posthog/releases/download/posthog-cli%2Fv<X.Y.Z>/posthog-cli-installer.sh" | sha256sum
ARG POSTHOG_CLI_VERSION=0.8.1
ARG POSTHOG_CLI_INSTALLER_SHA256=b1f1781a78a37930884db3ad412d9508a9ac015b01339455a7357cd0b23d9c92
ARG SYMBOL_UPLOAD_TRIGGER=""
RUN --mount=type=secret,id=posthog_upload_symbols_cli_api_key \
    --mount=type=cache,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,target=/usr/local/cargo/git,sharing=locked \
    if [ -z "$SYMBOL_UPLOAD_TRIGGER" ] || [ ! -s /run/secrets/posthog_upload_symbols_cli_api_key ]; then \
        echo "No symbol upload trigger/token; skipping native symbol upload"; \
    elif ( \
        curl --proto '=https' --tlsv1.2 -LsSf -o /tmp/posthog-cli-installer.sh \
            "https://github.com/PostHog/posthog/releases/download/posthog-cli%2Fv${POSTHOG_CLI_VERSION}/posthog-cli-installer.sh" && \
        echo "${POSTHOG_CLI_INSTALLER_SHA256}  /tmp/posthog-cli-installer.sh" | sha256sum -c - && \
        sh /tmp/posthog-cli-installer.sh && \
        export PATH="/root/.posthog:$PATH" && \
        export POSTHOG_CLI_TOKEN="$(cat /run/secrets/posthog_upload_symbols_cli_api_key)" && \
        export POSTHOG_CLI_ENV_ID=2 && \
        mkdir -p /tmp/posthog-symbols && \
        cp "target/release/$BIN" /tmp/posthog-symbols/ && \
        posthog-cli symbol-sets upload \
            --directory /tmp/posthog-symbols \
            --include-source \
    ); then \
        echo "Native debug symbols uploaded for $BIN"; \
    else \
        echo "WARNING: native symbol upload failed for $BIN; panics from this build may not symbolicate" >&2; \
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

# Opt-in stage for jumphost images (see bin/rust-jumphost) — not used by
# request-path services, which keep building the smaller `runtime` stage.
FROM runtime AS runtime-jumphost

USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends redis-tools awscli && \
    rm -rf /var/lib/apt/lists/*
USER nobody

# Keep the file's final stage equivalent to `runtime` so builds without an
# explicit `--target` (e.g. canary-flags-enable.yml, ad-hoc `docker build`)
# keep producing the minimal image instead of silently inheriting the larger
# jumphost layer.
FROM runtime AS default
