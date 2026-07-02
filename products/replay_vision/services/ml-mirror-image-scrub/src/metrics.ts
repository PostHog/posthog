// Prometheus counters + a minimal /metrics server so scrub failures and key/content mismatches are
// alertable, not just stdout log lines.
import http from 'node:http'
import { Counter, register } from 'prom-client'

export class ScrubMetrics {
    private static readonly scrubbed = new Counter({
        name: 'ml_mirror_image_scrub_scrubbed_total',
        help: 'Images scrubbed and buffered for a shard write',
    })
    private static readonly failed = new Counter({
        name: 'ml_mirror_image_scrub_failed_total',
        help: 'Images whose scrub failed (skipped; the reference resolves to nothing)',
    })
    private static readonly mismatch = new Counter({
        name: 'ml_mirror_image_scrub_key_content_mismatch_total',
        help: 'Messages dropped because the key hash did not match the value bytes (forged/corrupt key)',
    })
    private static readonly shardsWritten = new Counter({
        name: 'ml_mirror_image_scrub_shards_written_total',
        help: 'Shard objects (+ their parquet index) written to S3',
    })
    private static readonly shardImages = new Counter({
        name: 'ml_mirror_image_scrub_shard_images_total',
        help: 'Images written into shards',
    })
    private static readonly shardBytes = new Counter({
        name: 'ml_mirror_image_scrub_shard_bytes_total',
        help: 'Scrubbed image bytes written into shards',
    })

    public static incScrubbed(): void {
        this.scrubbed.inc()
    }
    public static incFailed(): void {
        this.failed.inc()
    }
    public static incMismatch(): void {
        this.mismatch.inc()
    }
    public static observeShard(images: number, bytes: number): void {
        this.shardsWritten.inc()
        this.shardImages.inc(images)
        this.shardBytes.inc(bytes)
    }
}

/** Serve /metrics (Prometheus) and /_health, /_ready. Returns a stop function. */
export function startMetricsServer(port = Number(process.env.METRICS_PORT ?? 9090)): () => void {
    const server = http.createServer((req, res) => {
        if (req.url === '/metrics') {
            register
                .metrics()
                .then((body) => {
                    res.setHeader('Content-Type', register.contentType)
                    res.end(body)
                })
                .catch(() => {
                    res.statusCode = 500
                    res.end()
                })
        } else if (req.url === '/_health' || req.url === '/_ready') {
            res.statusCode = 200
            res.end('ok')
        } else {
            res.statusCode = 404
            res.end()
        }
    })
    server.listen(port)
    return () => server.close()
}
