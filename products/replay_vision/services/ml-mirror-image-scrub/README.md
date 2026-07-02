# @posthog/ml-mirror-image-scrub

The **image-scrub sidecar**: an HTTP service that turns raw session-replay image bytes into scrubbed
bytes, and nothing else. It ships in two stages:

- **Stage 1 (this package):** a lean sharp-only downsample+blur (`src/blur.ts`), matching what the inline
  anonymizer already produces. No ML deps, so the image stays small.
- **Stage 2 (follow-up):** swap `blurOnly` for the native ML scrub (NSFW gate + face mosaic + text
  solid-fill) — heavy tfjs/onnxruntime deps that stay in **this** image and never reach the main
  workspace. The HTTP contract doesn't change, so the consumer is untouched.

The goal is to protect data labellers and reduce PII exposure in the training mirror.

## Why a sidecar

The work splits into two concerns with opposite needs:

- **Kafka consumption + S3 sharding** wants PostHog's battle-tested `KafkaConsumer` (node-rdkafka) and the
  standard metrics — so it lives **in the plugin-server** as an ingestion server mode
  (`nodejs/src/servers/ingestion-session-replay-ml-image-scrub-server.ts`).
- **The scrub compute** wants dependency isolation (Stage 2's ML runtime is ~hundreds of MB) — so it
  lives **here**, in a standalone image that is _not_ a pnpm-workspace member.

The consumer never imports this package; it **calls** it over localhost. A library import would drag the
ML deps into the workspace install; a process call doesn't. The two run as containers in the same pod.

## HTTP contract

```text
POST /scrub    body = raw image bytes            -> 200 scrubbed image bytes (application/octet-stream)
                                                     500 on undecodable/failed input (never passthrough)
                                                     503 when at IMAGE_SCRUB_CONCURRENCY (consumer retries)
GET  /_health, /_ready                           -> 200
GET  /metrics                                    -> Prometheus text (scrubbed/failed/rejected/duration)
```

Config (`src/config.ts`): `IMAGE_SCRUB_PORT` (9010), `IMAGE_SCRUB_CONCURRENCY` (8).

## Layout

`src/` is production (ships in the image); `dev/` is non-production. Production never imports from `dev/`.

```text
src/  (production — ships)
  server.ts    HTTP server: POST /scrub -> scrub bytes, + /_health, /metrics; bounded concurrency
  blur.ts      Stage-1 scrub: sharp-only downsample+blur (no ML deps)
  config.ts    port + concurrency from env
  metrics.ts   prom-client counters/histogram, served at /metrics

dev/  (non-production)
  server.test.ts   unit test: POST /scrub blurs, 500s on garbage, serves health+metrics
```

## Run

```bash
pnpm install
pnpm test:unit                                   # fast unit test (starts the server on an ephemeral port)
pnpm start                                        # the sidecar; POST an image to :9010/scrub
```

## Packaging / deployment

Owned by the `replay_vision` product, so it lives under `products/replay_vision/services/`. It is a
**standalone package, deliberately not registered in `pnpm-workspace.yaml`** — keeping it out of the
workspace keeps its (Stage-2) heavy ML deps out of the root lockfile and the shared plugin-server image.
It has its own `pnpm-lock.yaml`; `Dockerfile.ml-mirror-image-scrub` (repo root) installs
`--prod --frozen-lockfile` against it, so only `dependencies` (sharp, prom-client, tsx) land in the image.
It builds via `.github/workflows/ci-ml-mirror-image-scrub-container.yml` and deploys as a sidecar
container alongside the consumer.
