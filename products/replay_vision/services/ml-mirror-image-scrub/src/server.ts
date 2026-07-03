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

import { UndecodableImageError, blurOnly } from './blur.ts'
import { loadConfig } from './config.ts'
import { ScrubMetrics, register } from './metrics.ts'

class ConsumerHungUpError extends Error {}

/**
 * Stage-1 scrub. Stage 2 replaces the body with the ML pipeline; the (bytes -> bytes) shape is fixed.
 * `signal` aborts when the consumer hangs up: Stage 1 is a single libvips op that can't be interrupted
 * mid-flight, so we only check it at the boundary (skip before starting if the client is already gone);
 * the multi-stage Stage-2 pipeline threads the same signal between stages to bail out of long ML work.
 */
async function scrub(input: Buffer, signal: AbortSignal): Promise<Buffer> {
    if (signal.aborted) {
        throw new ConsumerHungUpError()
    }
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
        const stopTimer = ScrubMetrics.startTimer()
        // Abort in-progress work if the consumer hangs up before we respond: don't scrub for a dead socket
        // (and, in Stage 2, cut long ML work short). `res` fires 'close' once the response is done too, so
        // only treat it as an abort while we haven't finished writing.
        const controller = new AbortController()
        res.on('close', () => {
            if (!res.writableEnded) {
                controller.abort()
            }
        })
        // A write that loses the race with the client hanging up emits ECONNRESET here; swallow it so one
        // dropped connection can't take the sidecar down with an uncaught error.
        res.on('error', () => {})
        readBody(req)
            .then((body) => scrub(body, controller.signal))
            .then((out) => {
                if (controller.signal.aborted) {
                    ScrubMetrics.incAborted()
                    return
                }
                ScrubMetrics.incScrubbed()
                res.writeHead(200, { 'content-type': 'application/octet-stream' }).end(out)
            })
            .catch((e) => {
                if (controller.signal.aborted || e instanceof ConsumerHungUpError) {
                    ScrubMetrics.incAborted()
                    return
                }
                // 422 = the input isn't a decodable image: permanent, so the consumer skips it. 500 = an
                // internal/transient failure (libvips OOM, truncated body): the consumer retries and replays.
                if (e instanceof UndecodableImageError) {
                    ScrubMetrics.incUndecodable()
                    res.writeHead(422).end('undecodable image')
                    return
                }
                ScrubMetrics.incFailed()
                console.error(`scrub failed: ${String(e)}`)
                res.writeHead(500).end('scrub failed')
            })
            .finally(() => {
                inFlight -= 1
                stopTimer()
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
        process.on(sig, () => {
            // Force-exit backstop so we never hang past the pod's termination grace period.
            const force = setTimeout(() => process.exit(1), 10_000)
            force.unref()
            server.close(() => {
                clearTimeout(force)
                process.exit(0)
            })
            // Drop the consumer's idle keep-alive sockets so close() can complete; in-flight scrubs still drain.
            server.closeIdleConnections()
        })
    }
}

main()
