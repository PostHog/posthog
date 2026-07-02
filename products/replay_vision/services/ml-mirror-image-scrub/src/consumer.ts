/* eslint-disable no-console -- worker logs to stdout */
/**
 * Image-scrub consumer worker: reads raw images off the scrub topic (key = `image:{team}:{hash}`),
 * scrubs them, and batches the bytes into shard objects + a content-hash-keyed parquet index (see
 * shard-store.ts + README). Stage 1 scrub is the sharp-only blur (blur.ts); Stage 2 swaps in advancedScrub.
 *
 *   npm run consume   (needs the dev stack: Kafka + SeaweedFS; env overrides in config.ts)
 */
import { Kafka } from 'kafkajs'

import { ImageBatcher } from './batcher.ts'
import { blurOnly } from './blur.ts'
import { ensureBucket, ensureTopic, makeS3 } from './clients.ts'
import { loadConfig } from './config.ts'
import { hashImageBytes, isImageRef, parseImageRef } from './content-ref.ts'
import { ScrubMetrics, startMetricsServer } from './metrics.ts'
import { ImageShardStore, ScrubbedImage } from './shard-store.ts'

/** Parse + verify + scrub one message into a ScrubbedImage, or null to skip it. */
async function scrubImage(ref: string, raw: Buffer): Promise<ScrubbedImage | null> {
    // Reject bytes whose hash doesn't match the key's: content integrity, so the object a reference points
    // at always matches its content. Not a team-authorization check (the hash is content-only and unkeyed);
    // a producer forging another team's key is out of scope, this is an internal producer-only topic.
    const parsed = parseImageRef(ref)
    if (!parsed || hashImageBytes(raw) !== parsed.hash) {
        ScrubMetrics.incMismatch()
        return null
    }
    const bytes = await blurOnly(raw)
    ScrubMetrics.incScrubbed()
    return { teamId: parsed.teamId, hash: parsed.hash, bytes }
}

async function main(): Promise<void> {
    const cfg = loadConfig()
    const s3 = makeS3(cfg)
    const kafka = new Kafka({ clientId: 'ml-mirror-image-scrub', brokers: cfg.kafkaBrokers })
    // ensureBucket/ensureTopic are local-dev conveniences: in prod the bucket + topic are provisioned by
    // infra, and the IRSA role can't CreateBucket (ensureBucket would 403 and crash the pod on startup).
    // Static S3 creds are only set in local dev (see makeS3), so gate on that.
    if (cfg.s3.accessKeyId && cfg.s3.secretAccessKey) {
        await ensureBucket(s3, cfg.s3.bucket)
        await ensureTopic(kafka, cfg.topic)
    }
    const stopMetrics = startMetricsServer()

    const store = new ImageShardStore(s3, cfg.s3.bucket)
    const batcher = new ImageBatcher(store, cfg.flush, Date.now())

    const consumer = kafka.consumer({ groupId: cfg.consumerGroup })
    await consumer.connect()
    await consumer.subscribe({ topic: cfg.topic, fromBeginning: false })
    console.log(`consuming ${cfg.topic} (group ${cfg.consumerGroup}) -> s3://${cfg.s3.bucket} @ ${cfg.s3.endpoint}`)

    // Un-committed offsets accumulated across batches, committed only after a flush lands; autoCommit/autoResolve off so nothing commits ahead of a write.
    const pending = new Map<number, { topic: string; partition: number; offset: string }>()

    // Serialize flushes so the idle timer and eachBatch never overlap. Each run snapshots pending in the
    // same synchronous tick as the buffer swap (batcher.flush clears the buffer before its first await), so
    // a committed offset always covers a flushed image; offsets that arrive mid-flush stay pending.
    let flushChain: Promise<unknown> = Promise.resolve()
    function flushAndCommit(): Promise<void> {
        const run = flushChain.then(async () => {
            const offsets = [...pending.values()]
            await batcher.flush(Date.now()) // throws on write failure → no commit → Kafka replays
            if (offsets.length === 0) {
                return
            }
            await consumer.commitOffsets(offsets)
            for (const o of offsets) {
                if (pending.get(o.partition)?.offset === o.offset) {
                    pending.delete(o.partition)
                }
            }
        })
        flushChain = run.catch(() => {})
        return run
    }

    // eachBatch only fires on new traffic, so without this a partition that buffers then goes quiet would
    // hold those images until traffic resumes. shouldFlush gates on the same interval/size thresholds.
    const flushTimer = setInterval(
        () => {
            if (batcher.shouldFlush(Date.now())) {
                flushAndCommit().catch((e) => console.error(`periodic flush failed: ${String(e)}`))
            }
        },
        Math.max(1000, cfg.flush.flushIntervalMs)
    )
    flushTimer.unref?.()

    await consumer.run({
        autoCommit: false,
        eachBatchAutoResolve: false,
        eachBatch: async ({ batch, resolveOffset, heartbeat, isRunning, isStale }) => {
            for (const m of batch.messages) {
                if (!isRunning() || isStale()) {
                    break
                }
                const ref = m.key?.toString('utf8')
                if (ref && isImageRef(ref) && m.value) {
                    try {
                        const scrubbed = await scrubImage(ref, m.value)
                        if (scrubbed) {
                            batcher.add(scrubbed)
                        }
                    } catch (e) {
                        // One bad image is skipped (its reference resolves to nothing), acceptable for the mirror; metered, and the offset still advances.
                        ScrubMetrics.incFailed()
                        console.error(`${ref}: scrub failed: ${String(e)}`)
                    }
                }
                pending.set(batch.partition, {
                    topic: batch.topic,
                    partition: batch.partition,
                    offset: (Number(m.offset) + 1).toString(),
                })
                // Advance kafkajs past this message (autoResolve is off, so without this the same batch
                // reprocesses forever). Durability is separate: the offset isn't committed until its shard flushes.
                resolveOffset(m.offset)
                await heartbeat()
            }
            if (batcher.shouldFlush(Date.now())) {
                await flushAndCommit()
                await heartbeat()
            }
        },
    })

    // Graceful shutdown: disconnect finishes the in-flight batch; buffered-but-unflushed images have un-committed offsets, so they replay on restart.
    let shuttingDown = false
    for (const sig of ['SIGINT', 'SIGTERM'] as const) {
        process.on(sig, () => {
            if (shuttingDown) {
                return
            }
            shuttingDown = true
            console.log(`${sig} received, draining...`)
            clearInterval(flushTimer)
            const force = setTimeout(() => process.exit(1), 30_000)
            consumer
                .disconnect()
                .catch((e) => console.error(`disconnect error: ${String(e)}`))
                .finally(() => {
                    clearTimeout(force)
                    stopMetrics()
                    process.exit(0)
                })
        })
    }
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
