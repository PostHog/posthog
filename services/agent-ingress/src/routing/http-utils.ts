/**
 * Defensive HTTP middleware shared by every ingress route. Mirrors the
 * janitor's `src/http-utils.ts` so both services translate `ZodError` /
 * malformed JSON / `AmbiguousRevisionError` the same way.
 *
 * `requestLogger(log)` — first middleware. One structured line per request
 * on response completion, so every call leaves a trace.
 *
 * `asyncHandler(fn)` — Express 4 doesn't catch rejections returned from
 * async route handlers; they become `unhandledRejection`. Every async
 * route should be wrapped so its rejection lands in `next(err)`.
 *
 * `errorHandler(log)` — Final express middleware. Always returns JSON;
 * never an Express HTML stack trace. Add new typed-error mappings here
 * as they get thrown from new resolvers / triggers.
 */

import type { NextFunction, Request, RequestHandler, Response } from 'express'
import { ZodError } from 'zod'

import type { Logger } from '@posthog/agent-shared'

import { AmbiguousRevisionError } from './resolver'

/**
 * One structured log line per request, emitted when the response completes so
 * it carries the final status + total duration — the trail you need when an
 * ingress call misbehaves and there's otherwise nothing to grep for.
 *
 * Level tracks the outcome (5xx → error, 4xx → warn, else info). A
 * `request_start` line at `debug` makes in-flight / hung requests visible too.
 * `/healthz` probe spam is demoted to `debug` so the default `info` stream
 * stays readable — flip `LOG_LEVEL=debug` to see probes and starts.
 *
 * Listens on both `finish` and `close`: a client that aborts mid-response (a
 * dropped SSE `/listen`, a cancelled fetch) emits only `close`, and that's
 * exactly the case worth seeing — logged with `aborted: true`.
 */
export function requestLogger(log: Logger): RequestHandler {
    return (req, res, next) => {
        const start = process.hrtime.bigint()
        log.debug({ method: req.method, url: req.originalUrl }, 'request_start')
        let logged = false
        const emit = (): void => {
            if (logged) {
                return
            }
            logged = true
            const fields = {
                method: req.method,
                url: req.originalUrl,
                status: res.statusCode,
                duration_ms: Math.round((Number(process.hrtime.bigint() - start) / 1e6) * 10) / 10,
                ip: req.ip,
                forwarded_for: req.headers['x-forwarded-for'],
                length: res.getHeader('content-length'),
                ua: req.headers['user-agent'],
                // `finish` means the response was fully flushed; reaching `close`
                // first means the peer hung up mid-write.
                ...(res.writableFinished ? {} : { aborted: true }),
            }
            if (req.path === '/healthz') {
                log.debug(fields, 'request')
            } else if (res.statusCode >= 500) {
                log.error(fields, 'request')
            } else if (res.statusCode >= 400) {
                log.warn(fields, 'request')
            } else {
                log.info(fields, 'request')
            }
        }
        res.on('finish', emit)
        res.on('close', emit)
        next()
    }
}

export type AsyncRouteHandler = (req: Request, res: Response, next: NextFunction) => Promise<unknown> | unknown

export function asyncHandler(fn: AsyncRouteHandler): RequestHandler {
    return (req, res, next) => {
        Promise.resolve(fn(req, res, next)).catch(next)
    }
}

export function errorHandler(log: Logger) {
    // Express identifies error middleware by arity — must declare 4 params.
    return (err: unknown, req: Request, res: Response, _next: NextFunction): void => {
        if (res.headersSent) {
            // Response already started — can't send JSON now. Log + bail; the
            // socket will be closed by express. Better than crashing.
            log.error(
                { err: errMessage(err), stack: errStack(err), path: req.path, method: req.method },
                'error_after_response_started'
            )
            return
        }
        if (err instanceof AmbiguousRevisionError) {
            res.status(400).json({
                error: 'ambiguous_revision',
                prefix: err.prefix,
                application_id: err.applicationId,
                candidates: err.candidates,
                detail: 'Multiple revisions match this prefix; re-issue with a longer prefix.',
            })
            return
        }
        if (err instanceof ZodError) {
            res.status(400).json({
                error: 'invalid_request',
                issues: err.issues.map((i) => ({ path: i.path, message: i.message, code: i.code })),
            })
            return
        }
        if (err instanceof SyntaxError && 'body' in (err as object)) {
            // express.json() threw on a malformed JSON body.
            res.status(400).json({ error: 'invalid_json' })
            return
        }
        log.error(
            { err: errMessage(err), stack: errStack(err), path: req.path, method: req.method },
            'unhandled_route_error'
        )
        res.status(500).json({ error: 'internal_error' })
    }
}

function errMessage(err: unknown): string {
    return err instanceof Error ? err.message : String(err)
}

function errStack(err: unknown): string | undefined {
    return err instanceof Error ? err.stack : undefined
}
