/* eslint-disable no-console -- sidecar logs to stdout */
/**
 * Image-scrub sidecar: an HTTP service that turns raw image bytes into scrubbed image bytes and nothing
 * else. The workspace consumer owns Kafka + S3; it POSTs each image here and writes back what we return.
 *
 * Stage 1 scrub is the sharp-only blur (blur.ts). Stage 2 swaps `scrub` for the native ML pipeline
 * (NSFW gate + face mosaic + text solid-fill) — heavy tfjs/onnxruntime deps that stay in this image and
 * never reach the main workspace. The HTTP contract doesn't change, so the consumer is untouched.
 *
 *   POST /scrub   body = raw image bytes            -> 200 scrubbed image bytes (application/octet-stream)
 *   GET  /_health, /_ready                          -> 200
 *   GET  /metrics                                   -> Prometheus text
 */
import { createServer } from 'node:http'

import { blurOnly } from './blur.ts'
import { loadConfig } from './config.ts'
import { ScrubMetrics, register } from './metrics.ts'

/** Stage-1 scrub. Stage 2 replaces the body with the ML pipeline; the (bytes -> bytes) shape is fixed. */
async function scrub(input: Buffer): Promise<Buffer> {
    return blurOnly(input)
}

async function readBody(req: NodeJS.ReadableStream): Promise<Buffer> {
    const chunks: Buffer[] = []
    for await (const chunk of req) {
        chunks.push(chunk as Buffer)
    }
    return Buffer.concat(chunks)
}

export function startServer(port: number, maxConcurrency: number): ReturnType<typeof createServer> {
    let inFlight = 0
    const server = createServer((req, res) => {
        const url = req.url ?? '/'
        if (req.method === 'GET' && (url === '/_health' || url === '/_ready')) {
            res.writeHead(200).end('ok')
            return
        }
        if (req.method === 'GET' && url === '/metrics') {
            register
                .metrics()
                .then((body) => res.writeHead(200, { 'content-type': register.contentType }).end(body))
                .catch(() => res.writeHead(500).end())
            return
        }
        if (req.method !== 'POST' || url !== '/scrub') {
            res.writeHead(404).end()
            return
        }
        // Shed load rather than pile unbounded sharp work behind the event loop; the consumer retries.
        if (inFlight >= maxConcurrency) {
            ScrubMetrics.incRejected()
            res.writeHead(503).end('busy')
            return
        }
        inFlight += 1
        const done = ScrubMetrics.startTimer()
        readBody(req)
            .then((body) => scrub(body))
            .then((out) => {
                ScrubMetrics.incScrubbed()
                res.writeHead(200, { 'content-type': 'application/octet-stream' }).end(out)
            })
            .catch((e) => {
                ScrubMetrics.incFailed()
                console.error(`scrub failed: ${String(e)}`)
                res.writeHead(500).end('scrub failed')
            })
            .finally(() => {
                inFlight -= 1
                done()
            })
    })
    // Bind loopback only: the consumer shares the pod's network namespace, so it reaches us via localhost,
    // but nothing on the pod IP can POST images to /scrub.
    server.listen(port, '127.0.0.1', () =>
        console.log(`image-scrub sidecar listening on 127.0.0.1:${port} (maxConcurrency ${maxConcurrency})`)
    )
    return server
}

function main(): void {
    const cfg = loadConfig()
    const server = startServer(cfg.port, cfg.maxConcurrency)
    for (const sig of ['SIGINT', 'SIGTERM'] as const) {
        process.on(sig, () => server.close(() => process.exit(0)))
    }
}

main()
