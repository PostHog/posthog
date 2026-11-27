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
# They go to the internal PostHog project (HOG_PROJECT_ID=2 on US cloud),
# the same project the frontend sourcemap upload in the root Dockerfile targets.
# Runs only when CI mounts the job's OIDC request credentials (master builds on
# the canonical deploy repo, see _rust-build-images.yml); PR and local builds skip it.
# hog exchanges the OIDC token for a short-lived PostHog token, which needs a
# trust policy for the deploy repo in project 2. GITHUB_ACTIONS selects that
# exchange. The other GitHub variables stay unset on purpose: without GITHUB_SHA
# hog stamps no release, which is what the next paragraph needs.
# Upload failures warn instead of failing the build: symbols must never block
# shipping an image. The cargo registry cache mounts make dependency sources
# visible to --include-source at the paths DWARF records for them.
# No release stamping: symbolication resolves by GNU build id alone, and the
# amd64/arm64 builds run concurrently, so a lookup-then-create release flow
# would race and drop one platform's upload.
#
# SYMBOL_UPLOAD_TRIGGER exists because secret mounts are not part of the layer
# cache key: without it, a PR build's skipped-upload layer could be reused by a
# master build and silently skip the upload. CI sets it to the unique run id
# when it mounts the credentials, so those builds always re-execute this layer;
# builds without them keep a constant empty value and stay cached.
#
# hog is pinned to an immutable release and checksum-verified before use. The
# glibc archives match this Debian builder. hog runs hog-worker from its own
# folder, so both files stay together. To upgrade, change HOG_VERSION and copy
# the two linux checksums from that release's SHA256SUMS:
#   https://github.com/PostHog/posthog/releases/download/hog%2Fv<X.Y.Z>/SHA256SUMS
ARG HOG_VERSION=0.3.0
ARG HOG_SHA256_AMD64=9dff37a41ec5bf947c190fc4760e95a051be9ea7744eb3d0f4a4e7be695674bc
ARG HOG_SHA256_ARM64=35a0a6de2dfd476e2e594002fa7eb5b90d3b2a2ec578983075706df1c1b5b038
ARG TARGETARCH
ARG SYMBOL_UPLOAD_TRIGGER=""
RUN --mount=type=secret,id=actions_id_token_request_url \
    --mount=type=secret,id=actions_id_token_request_token \
    --mount=type=cache,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,target=/usr/local/cargo/git,sharing=locked \
    if [ -z "$SYMBOL_UPLOAD_TRIGGER" ] || [ ! -s /run/secrets/actions_id_token_request_token ]; then \
        echo "No symbol upload trigger/credentials; skipping native symbol upload"; \
    elif ( \
        case "$TARGETARCH" in \
            amd64) hog_target=linux-x64 hog_sha256="$HOG_SHA256_AMD64" ;; \
            arm64) hog_target=linux-arm64 hog_sha256="$HOG_SHA256_ARM64" ;; \
            *) echo "No hog build for $TARGETARCH" >&2; exit 1 ;; \
        esac && \
        curl --proto '=https' --tlsv1.2 -fsSL --retry 5 --retry-all-errors --connect-timeout 10 -o /tmp/hog.tar.gz \
            "https://github.com/PostHog/posthog/releases/download/hog%2Fv${HOG_VERSION}/hog-${hog_target}.tar.gz" && \
        echo "${hog_sha256}  /tmp/hog.tar.gz" | sha256sum -c - && \
        mkdir -p /tmp/hog && tar -xzf /tmp/hog.tar.gz -C /tmp/hog && \
        mkdir -p /tmp/posthog-symbols && \
        cp "target/release/$BIN" /tmp/posthog-symbols/ && \
        GITHUB_ACTIONS=true \
        ACTIONS_ID_TOKEN_REQUEST_URL="$(cat /run/secrets/actions_id_token_request_url)" \
        ACTIONS_ID_TOKEN_REQUEST_TOKEN="$(cat /run/secrets/actions_id_token_request_token)" \
        HOG_PROJECT_ID=2 HOG_NO_TELEMETRY=1 HOG_NO_UPDATE_CHECK=1 \
        /tmp/hog/hog error-tracking upload /tmp/posthog-symbols --include-source \
    ); then \
        echo "Native debug symbols uploaded for $BIN"; \
    else \
        echo "WARNING: native symbol upload failed for $BIN; panics from this build may not symbolicate" >&2; \
    fi

FROM debian:bookworm-slim AS deploy-requirements

# The deploy requirements manifest of this image (tools/deploy-requirements), for the
# deploy-time check in bin/deploy-requirements-check.
# SQLX_DATABASES comes from the image's sqlx_databases entry in .github/rust-images.yml.
ARG SQLX_DATABASES=""
WORKDIR /src
COPY persons_migrations ./persons_migrations
COPY behavioral_cohorts_migrations ./behavioral_cohorts_migrations
COPY cyclotron-node-migrations ./cyclotron-node-migrations
COPY flags_read_store_migrations ./flags_read_store_migrations
COPY bin/write-deploy-requirements ./write-deploy-requirements
RUN sh ./write-deploy-requirements "$SQLX_DATABASES" /schema-requirements.json /src

FROM debian:bookworm-slim AS runtime

# AWS RDS global CA bundle — all root and intermediate CAs for TLS verification.
# To update: download the bundle, recompute the hash with sha256sum, and replace the value below.
#   curl -fsS "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem" | sha256sum
ARG RDS_CA_BUNDLE_SHA256=90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b

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
    rm -rf ./share && \
    curl -fsS -o /tmp/rds-combined-ca-bundle.crt \
        "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem" && \
    echo "${RDS_CA_BUNDLE_SHA256}  /tmp/rds-combined-ca-bundle.crt" | sha256sum -c - && \
    mv /tmp/rds-combined-ca-bundle.crt /usr/local/share/ca-certificates/rds-combined-ca-bundle.crt && \
    update-ca-certificates

ARG BIN
ENV BIN=$BIN
WORKDIR /app

USER nobody

COPY --from=deploy-requirements /schema-requirements.json /app/schema-requirements.json
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
