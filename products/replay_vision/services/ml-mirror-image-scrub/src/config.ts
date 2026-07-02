// Runtime config for the consumer worker + local produce CLI; defaults point at the dev stack
// (Kafka :9092, SeaweedFS S3 :8333), override via env elsewhere.

/** Keep in sync with KAFKA_SESSION_REPLAY_IMAGE_SCRUB in kafka-topics.ts + terraform. The nodejs producer
 *  prefixes this with KAFKA_PREFIX, so where that is non-empty the deployment must set IMAGE_SCRUB_TOPIC to
 *  the fully-resolved (prefixed) name or consumer and producer use different topics (empty in prod today). */
export const IMAGE_SCRUB_TOPIC = 'session_replay_image_scrub'

export interface Config {
    kafkaBrokers: string[]
    topic: string
    consumerGroup: string
    // Keys optional: unset in prod so makeS3 lets the AWS SDK default chain resolve the IRSA role; set
    // locally for SeaweedFS/MinIO.
    s3: { endpoint: string; region: string; bucket: string; accessKeyId?: string; secretAccessKey?: string }
    // Buffer scrubbed images until any threshold trips, then write one shard + index per team. Bigger
    // shards = fewer, cheaper S3 writes; the interval bounds worst-case latency.
    flush: { maxImages: number; maxBytes: number; flushIntervalMs: number }
}

export function loadConfig(): Config {
    return {
        kafkaBrokers: (process.env.KAFKA_BROKERS ?? 'localhost:9092').split(','),
        topic: process.env.IMAGE_SCRUB_TOPIC ?? IMAGE_SCRUB_TOPIC,
        consumerGroup: process.env.IMAGE_SCRUB_GROUP ?? 'ml-mirror-image-scrub-consumer',
        flush: {
            maxImages: Number(process.env.IMAGE_SCRUB_FLUSH_MAX_IMAGES ?? 1000),
            maxBytes: Number(process.env.IMAGE_SCRUB_FLUSH_MAX_BYTES ?? 128 * 1024 * 1024),
            flushIntervalMs: Number(process.env.IMAGE_SCRUB_FLUSH_INTERVAL_MS ?? 30_000),
        },
        // Read standard object-storage env so prod points at SESSION_RECORDING_V2_S3 / OBJECT_STORAGE_*,
        // not a hardcoded endpoint. Default to SeaweedFS; for a local MinIO-style `objectstorage` set
        // S3_ENDPOINT=http://localhost:19000.
        s3: {
            endpoint: process.env.OBJECT_STORAGE_ENDPOINT ?? process.env.S3_ENDPOINT ?? 'http://localhost:8333',
            region: process.env.S3_REGION ?? 'us-east-1',
            bucket: process.env.OBJECT_STORAGE_BUCKET ?? process.env.S3_BUCKET ?? 'posthog',
            accessKeyId: process.env.OBJECT_STORAGE_ACCESS_KEY_ID ?? process.env.S3_ACCESS_KEY_ID,
            secretAccessKey: process.env.OBJECT_STORAGE_SECRET_ACCESS_KEY ?? process.env.S3_SECRET_ACCESS_KEY,
        },
    }
}
