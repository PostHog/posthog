// S3 helpers + topic-ensure for the consumer worker and local produce CLI. Producer-side Redis dedup +
// Kafka producing live in the nodejs ml-mirror pipeline; the consumer only reads routed images off the
// topic and writes the scrubbed result to S3.
import { CreateBucketCommand, S3Client } from '@aws-sdk/client-s3'
import type { Kafka } from 'kafkajs'

import type { Config } from './config.ts'

/** Idempotently create the topic so a fresh local stack works without editing the dev compose; lists
 *  first so a pre-existing topic doesn't log a broker "already exists" error. */
export async function ensureTopic(kafka: Kafka, topic: string): Promise<void> {
    const admin = kafka.admin()
    await admin.connect()
    try {
        const existing = await admin.listTopics()
        if (!existing.includes(topic)) {
            await admin.createTopics({ topics: [{ topic, numPartitions: 1, replicationFactor: 1 }] })
        }
    } finally {
        await admin.disconnect()
    }
}

export function makeS3(cfg: Config): S3Client {
    const { accessKeyId, secretAccessKey } = cfg.s3
    return new S3Client({
        endpoint: cfg.s3.endpoint,
        region: cfg.s3.region,
        forcePathStyle: true, // required for SeaweedFS / MinIO
        // Static keys only when both are set (local dev); else omit so the SDK's default chain resolves
        // the in-cluster IRSA role, never falling back to dev creds.
        ...(accessKeyId && secretAccessKey ? { credentials: { accessKeyId, secretAccessKey } } : {}),
    })
}

/** Create the bucket if missing (MinIO errors on PUT to a missing bucket; SeaweedFS auto-creates). */
export async function ensureBucket(s3: S3Client, bucket: string): Promise<void> {
    try {
        await s3.send(new CreateBucketCommand({ Bucket: bucket }))
    } catch (e) {
        const code = (e as { name?: string }).name ?? ''
        if (!/BucketAlreadyOwnedByYou|BucketAlreadyExists/.test(code)) {
            const status = (e as { $metadata?: { httpStatusCode?: number } }).$metadata?.httpStatusCode
            if (status !== 409) {
                throw e
            }
        }
    }
}
