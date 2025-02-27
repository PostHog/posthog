# Taken from: https://depot.dev/docs/container-builds/how-to-guides/optimal-dockerfiles/rust-dockerfile
FROM rust:1.82 AS base
RUN cargo install --locked cargo-chef sccache
ENV RUSTC_WRAPPER=sccache SCCACHE_DIR=/sccache

FROM base AS planner
WORKDIR /app
ARG BIN

COPY . .
RUN cargo chef prepare --recipe-path recipe.json --bin $BIN

FROM base AS builder
ARG BIN

# Ensure working C compile setup (not installed by default in arm64 images)
RUN apt update && apt install build-essential libssl-dev cmake -y

COPY --from=planner /app/recipe.json recipe.json
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    --mount=type=cache,target=$SCCACHE_DIR,sharing=locked \
    cargo chef cook --release --recipe-path recipe.json --bin $BIN

COPY . .
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    --mount=type=cache,target=$SCCACHE_DIR,sharing=locked \
    cargo build --release --bin $BIN

FROM debian:bookworm-slim AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libssl-dev "ca-certificates" \
    && \
    rm -rf /var/lib/apt/lists/*

ARG BIN
ENV BIN=$BIN
WORKDIR /app

USER nobody

COPY --from=builder /app/target/release/$BIN /usr/local/bin
ENTRYPOINT ["/bin/sh", "-c", "/usr/local/bin/$BIN"]
