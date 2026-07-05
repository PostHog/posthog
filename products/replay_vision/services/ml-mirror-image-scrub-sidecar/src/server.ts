/* eslint-disable no-console -- sidecar logs to stdout */
import express, { type NextFunction, type Request, type Response } from 'express'
import { type Server } from 'node:http'

import { UndecodableImageError, blurOnly } from './blur.ts'
import { ScrubMetrics, register } from './metrics.ts'

class ConsumerHungUpError extends Error {}

async function scrub(input: Buffer, signal: AbortSignal): Promise<Buffer> {
    if (signal.aborted) {
        throw new ConsumerHungUpError()
    }
    return blurOnly(input)
}

export function startServer(port: number, maxConcurrency: number, maxBodyBytes: number): Server {
    let inFlight = 0
    const app = express()
    app.disable('x-powered-by')
    app.disable('etag')

    app.get(['/_health', '/_ready'], (_req, res) => {
        res.status(200).send('ok')
    })

    app.get('/metrics', (_req, res, next) => {
        register
            .metrics()
            .then((body) => res.set('Content-Type', register.contentType).send(body))
            .catch(next)
    })

    const shedIfBusy = (_req: Request, res: Response, next: NextFunction): void => {
        if (inFlight >= maxConcurrency) {
            ScrubMetrics.incRejected()
            res.status(503).send('busy')
            return
        }
        inFlight += 1
        res.once('close', () => {
            inFlight -= 1
        })
        next()
    }

    app.post('/scrub', shedIfBusy, express.raw({ type: () => true, limit: maxBodyBytes }), (req, res, next) => {
        const body = req.body
        if (!Buffer.isBuffer(body)) {
            next(new UndecodableImageError('request body is not image bytes'))
            return
        }
        const stopTimer = ScrubMetrics.startTimer()
        const controller = new AbortController()
        res.on('close', () => {
            if (!res.writableEnded) {
                controller.abort()
            }
        })
        res.on('error', () => {})
        scrub(body, controller.signal)
            .then((out) => {
                if (controller.signal.aborted) {
                    ScrubMetrics.incAborted()
                    return
                }
                ScrubMetrics.incScrubbed()
                ScrubMetrics.observeOutputBytes(out.length)
                res.set('Content-Type', 'application/octet-stream').send(out)
            })
            .catch(next)
            .finally(() => stopTimer())
    })

    app.use((err: Error & { status?: number; type?: string }, _req: Request, res: Response, _next: NextFunction) => {
        if (err instanceof ConsumerHungUpError) {
            ScrubMetrics.incAborted()
            return
        }
        // Already responded, or the socket died after a partial success write: don't double-count as failed.
        if (res.writableEnded || !res.writable) {
            return
        }
        // express.raw over-limit lands here as 413: permanent, the consumer skips it.
        if (err.status === 413 || err.type === 'entity.too.large') {
            ScrubMetrics.incTooLarge()
            res.status(413).send('body too large')
            return
        }
        if (err instanceof UndecodableImageError) {
            ScrubMetrics.incUndecodable()
            res.status(422).send('undecodable image')
            return
        }
        ScrubMetrics.incFailed()
        console.error(`scrub failed: ${String(err)}`)
        res.status(500).send('scrub failed')
    })

    // Loopback only: the consumer shares the pod netns; the pod IP must not expose /scrub.
    const server = app.listen(port, '127.0.0.1', () =>
        console.log(`image-scrub sidecar listening on 127.0.0.1:${port} (maxConcurrency ${maxConcurrency})`)
    )
    server.on('error', (err) => {
        console.error(`image-scrub sidecar server error: ${String(err)}`)
        process.exit(1)
    })
    return server
}
