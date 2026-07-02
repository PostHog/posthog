# @posthog/ml-mirror-image-scrub

Consumer worker that scrubs inlined images for the session-replay ML-training mirror and batches them
into shard objects + a content-hash parquet index in S3. It ships in two stages:

- **Stage 1 (this package):** a lean sharp-only downsample+blur (`src/blur.ts`), matching what the
  inline anonymizer already produces. No ML deps, so the worker image stays small. This proves the
  plumbing — its own image, the Kafka topic, the producer's batched Redis dedup, and the batched
  shard + index writes.
- **Stage 2 (follow-up PR):** swap the consumer's `blurOnly` for the native ML scrub (NSFW gate +
  face mosaic + text solid-fill), and add those ML libraries as `dependencies`.

The goal is to protect data labellers and reduce PII exposure in the training mirror.

## Two sides: producer (nodejs) and consumer (this package)

The **producer** lives in the ml-mirror anonymize pipeline in nodejs
(`nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror/image-scrub/`). Per inlined image it decides:

| image                                        | route         | handling                                                                                                                              |
| -------------------------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| tiny (≤16px long side)                       | `passthrough` | left untouched — below the detector floor, so scrubbing finds nothing, and these icons/logos are high-signal training data            |
| canvas (`<canvas>` pixels, canvas mutations) | `cheap`       | existing in-process downsample+blur — canvas is dynamic and dedups ~never, so it is **never produced** to the topic                   |
| `<img>` / media raster                       | `advanced`    | replace with `image:{team}:{hash}`, dedup in Redis (`SET NX`, 24h), post raw bytes to the topic; the consumer scrubs and writes to S3 |
| oversize (> ~1MB, won't fit the topic)       | `cheap`       | in-process blur fallback                                                                                                              |

So only advanced-route `<img>`/media raster reaches the topic — this **consumer** package reads those
raw images, scrubs them, and batches the scrubbed bytes into shards (below). It never routes and never
sees canvas. The `image:{team}:{hash}` reference is team-scoped so storage stays per-tenant. The consumer
shares only the `content-ref` contract with the producer; a golden-vector test pins it on both sides
(see `dev/content-ref.test.ts`).

## Storage: shards + a content-hash index

Writing one S3 object per image would explode request costs (a page can inline hundreds of images).
Instead, the consumer **batches** scrubbed images and flushes them as two artifacts per team per flush
(the write-heavy pattern the ml-mirror block-metadata sink already uses):

```text
scrubbed-images/team_id={team}/shards/{node}-{ts}-{seq}.bin      raw concat of scrubbed image bytes
scrubbed-images/team_id={team}/index/{node}-{ts}-{seq}.parquet   rows: hash, shard, offset, length
```

- **Shard**: an opaque concatenation of scrubbed PNG bytes.
- **Index** (parquet, Snappy): one row per image mapping the content `hash` to its `(shard, offset, length)`.

Flush triggers: `IMAGE_SCRUB_FLUSH_MAX_IMAGES` (1000), `..._MAX_BYTES` (128 MiB), or `..._INTERVAL_MS`
(30 s). Kafka offsets are committed **only after** a flush lands in S3 (manual commit, no auto-commit),
so a failed write or a crash replays the un-committed window — at-least-once. A redelivered image just
gets written into a fresh shard; the reader dedups by hash, and a shard orphaned by a mid-write failure
is invisible (no index points at it).

**Read contract** (training / playback side): given `image:{team}:{hash}` from the recording, query the
team's index for `hash` → `(shard, offset, length)`, then S3 `GetObject(shard, Range: offset..offset+length)`.
Because index lookups are by content hash (not replay id), the same image is fetched once regardless of
how many recordings reference it.

## Layout

`src/` is production (ships in the consumer worker); `dev/` is everything non-production. Production
never imports from `dev/`.

```text
src/  (production — ships)
  consumer.ts     consumer worker: read topic -> scrub -> batch into shards (manual offset commit)
  blur.ts         Stage-1 scrub: sharp-only downsample+blur (no ML deps)
  shard-store.ts  write a team's images as one shard blob + one parquet index (hash -> shard/offset/length)
  batcher.ts      accumulate scrubbed images across batches; flush on count/bytes/interval
  clients.ts      S3 client + idempotent bucket/topic ensure
  config.ts       env-driven runtime config (Kafka, S3, flush thresholds)
  content-ref.ts  the shared contract: image:{team}:{hash} hash/build/parse (matches the producer)
  metrics.ts      prom-client counters + a /metrics server (scrubbed/failed/mismatch/shards)

dev/  (non-production)
  content-ref.test.ts  batcher.test.ts  shard-store.test.ts   unit tests (npm run test:unit)
  produce.ts           thin CLI that posts one image to the topic to exercise the consumer (npm run produce)
```

## Run

```bash
npm install
npm run test:unit    # fast unit tests (no network)
npm run consume      # the consumer worker; `npm run produce -- <img> <team>` to feed it
```

## Packaging / deployment

This worker is owned by the `replay_vision` product, so it lives under
`products/replay_vision/services/` (a service the product deploys — see `docs/internal/monorepo-layout.md`).
It is a **standalone package, deliberately not registered in `pnpm-workspace.yaml`**: it has no
`workspace:*` deps, so keeping it out of the workspace keeps its deps out of the root lockfile and out
of the shared plugin-server image (`nodejs/package.json` ships to every pod). It has its own
`pnpm-lock.yaml`, and `Dockerfile.ml-mirror-image-scrub` (at the repo root) installs
`--prod --frozen-lockfile` against it — so only `dependencies` (sharp, kafkajs, aws-sdk, @dsnp/parquetjs,
prom-client, tsx) land in the image.

The image builds and deploys via `.github/workflows/ci-ml-mirror-image-scrub-container.yml`, mirroring
`recording-rasterizer` (Depot build -> ECR/ghcr push -> `repository_dispatch` to the charts repo).
