/* eslint-disable no-console -- sidecar logs to stdout */
import { type IncomingMessage, createServer } from 'node:http'

import { UndecodableImageError, blurOnly } from './blur.ts'
import { ScrubMetrics, register } from './metrics.ts'

class ConsumerHungUpError extends Error {}
class BodyTooLargeError extends Error {}

async function scrub(input: Buffer, signal: AbortSignal): Promise<Buffer> {
    if (signal.aborted) {
        throw new ConsumerHungUpError()
    }
    return blurOnly(input)
}

async function readBody(req: IncomingMessage, maxBytes: number): Promise<Buffer> {
    if (Number(req.headers['content-length']) > maxBytes) {
        throw new BodyTooLargeError()
    }
    const chunks: Buffer[] = []
    let total = 0
    for await (const chunk of req) {
        total += (chunk as Buffer).length
        if (total > maxBytes) {
            throw new BodyTooLargeError()
        }
        chunks.push(chunk as Buffer)
    }
    return Buffer.concat(chunks)
}

export function startServer(
    port: number,
    maxConcurrency: number,
    maxBodyBytes: number
): ReturnType<typeof createServer> {
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
        if (inFlight >= maxConcurrency) {
            ScrubMetrics.incRejected()
            res.writeHead(503).end('busy')
            return
        }
        inFlight += 1
        const stopTimer = ScrubMetrics.startTimer()
        const controller = new AbortController()
        res.on('close', () => {
            if (!res.writableEnded) {
                controller.abort()
            }
        })
        res.on('error', () => {})
        readBody(req, maxBodyBytes)
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
                if (e instanceof BodyTooLargeError) {
                    ScrubMetrics.incTooLarge()
                    res.writeHead(413).end('body too large')
                    return
                }
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
    server.on('error', (err) => {
        console.error(`image-scrub sidecar server error: ${String(err)}`)
        process.exit(1)
    })
    // Loopback only: the consumer shares the pod netns; the pod IP must not expose /scrub.
    server.listen(port, '127.0.0.1', () =>
        console.log(`image-scrub sidecar listening on 127.0.0.1:${port} (maxConcurrency ${maxConcurrency})`)
    )
    return server
}
