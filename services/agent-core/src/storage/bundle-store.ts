import { GetObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { createHash } from 'node:crypto'

export interface BundleStoreConfig {
    endpoint: string
    region: string
    bucket: string
    accessKeyId: string
    secretAccessKey: string
    /** Path-style required for MinIO; defaults to true. */
    forcePathStyle?: boolean
}

/**
 * Reads a config from environment variables matching PostHog's Django defaults
 * for object storage. Local dev points at the MinIO container that ships with
 * docker-compose; production overrides via env.
 */
export function bundleStoreConfigFromEnv(env: NodeJS.ProcessEnv = process.env): BundleStoreConfig {
    return {
        endpoint: env.OBJECT_STORAGE_ENDPOINT ?? 'http://localhost:19000',
        region: env.OBJECT_STORAGE_REGION ?? 'us-east-1',
        bucket: env.OBJECT_STORAGE_BUCKET ?? 'posthog',
        accessKeyId: env.OBJECT_STORAGE_ACCESS_KEY_ID ?? 'object_storage_root_user',
        secretAccessKey: env.OBJECT_STORAGE_SECRET_ACCESS_KEY ?? 'object_storage_root_password',
        forcePathStyle: true,
    }
}

/**
 * Pulls agent bundles out of object storage. Pointed at MinIO locally (same
 * bucket Django uploads to via the presigned-POST flow in deploys.py) and at
 * real S3 in production. Verifies SHA-256 if the caller provides one — the
 * digest is recorded on the revision row at upload time.
 */
export class BundleStore {
    private readonly client: S3Client
    readonly bucket: string

    constructor(config: BundleStoreConfig) {
        this.bucket = config.bucket
        this.client = new S3Client({
            endpoint: config.endpoint,
            region: config.region,
            credentials: {
                accessKeyId: config.accessKeyId,
                secretAccessKey: config.secretAccessKey,
            },
            forcePathStyle: config.forcePathStyle ?? true,
        })
    }

    async downloadBundle(key: string, expectedSha256?: string): Promise<Buffer> {
        const out = await this.client.send(new GetObjectCommand({ Bucket: this.bucket, Key: key }))
        if (!out.Body) {
            throw new Error(`bundle ${key} returned empty body`)
        }
        const chunks: Buffer[] = []
        // The SDK returns a Node Readable here (we never run this in the browser).
        for await (const chunk of out.Body as AsyncIterable<Uint8Array>) {
            chunks.push(Buffer.from(chunk))
        }
        const body = Buffer.concat(chunks)
        if (expectedSha256) {
            const actual = createHash('sha256').update(body).digest('hex')
            if (actual !== expectedSha256) {
                throw new Error(`bundle ${key} sha256 mismatch: expected ${expectedSha256}, got ${actual}`)
            }
        }
        return body
    }

    destroy(): void {
        this.client.destroy()
    }
}
