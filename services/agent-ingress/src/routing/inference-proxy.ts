/**
 * Session-scoped inference proxy (agent-sandbox-tiers.md §8). The tier-2
 * coding sandbox reaches the model ONLY through here:
 *
 *   sandbox (agent-server) ──session token──▶ this proxy ──gateway key──▶ ai-gateway
 *
 * The sandbox holds an audience-bound session capability token (see
 * `inference-token.ts` in agent-shared) — never the real gateway credential.
 * This route verifies the token statelessly, confirms the session row is
 * still live (`state = 'running'`), swaps in the real key, and streams the
 * gateway's response back. Ending or stopping the session kills further
 * inference with no upstream revocation — this is the cost kill switch.
 *
 * Fail-closed: only the model-call paths the harness actually uses are
 * forwarded; everything else 404s without touching the upstream.
 */

import express, { NextFunction, Request, Response, Router } from 'express'
import { Readable } from 'node:stream'
import type { ReadableStream as WebReadableStream } from 'node:stream/web'

import type { HttpFetcher, Logger, SessionQueue } from '@posthog/agent-shared'
import { verifyInferenceProxyToken } from '@posthog/agent-shared'

import { asyncHandler } from './http-utils'

/** Upstream paths the harness's model SDKs legitimately call. */
const ALLOWED: { method: 'GET' | 'POST'; path: string }[] = [
    { method: 'GET', path: '/v1/models' },
    { method: 'POST', path: '/v1/messages' },
    { method: 'POST', path: '/v1/messages/count_tokens' },
    { method: 'POST', path: '/v1/chat/completions' },
]

/** Request headers forwarded upstream — auth is deliberately NOT among them. */
const FORWARD_REQUEST_HEADERS = ['content-type', 'accept', 'anthropic-version', 'anthropic-beta']

/** A model stream can run for minutes; override the HTTP client's 30s default. */
const UPSTREAM_TIMEOUT_MS = 600_000

export interface InferenceProxyConfig {
    /** Shared `AGENT_INTERNAL_SIGNING_KEY` — verifies the session token. */
    signingKey: string
    /** ai-gateway root (no trailing /v1). */
    gatewayUrl: string
    /** The real gateway credential — attached proxy-side, never in tier 2. */
    gatewayKey: string
    /** Direct (cluster-internal) HTTP client for the gateway hop. */
    http: HttpFetcher
}

export interface InferenceProxyDeps extends InferenceProxyConfig {
    queue: SessionQueue
    log: Logger
}

/** Bearer first (ANTHROPIC_AUTH_TOKEN), then x-api-key (ANTHROPIC_API_KEY). */
function extractToken(req: Request): string | null {
    const auth = req.headers.authorization
    if (auth?.startsWith('Bearer ')) {
        return auth.slice('Bearer '.length)
    }
    const apiKey = req.headers['x-api-key']
    return typeof apiKey === 'string' && apiKey.length > 0 ? apiKey : null
}

export function inferenceProxyRouter(deps: InferenceProxyDeps): Router {
    const router = Router()
    const gatewayRoot = deps.gatewayUrl.replace(/\/$/, '')

    // The body must reach the gateway byte-for-byte (and may be large);
    // capture it raw instead of letting the app-level JSON parser eat it.
    router.use(express.raw({ type: () => true, limit: '10mb' }))

    const authenticate = asyncHandler(async (req: Request, res: Response, next: NextFunction): Promise<void> => {
        const token = extractToken(req)
        if (!token) {
            res.status(401).json({ error: 'missing_token' })
            return
        }
        let sessionId: string
        try {
            sessionId = (await verifyInferenceProxyToken({ token, signingKey: deps.signingKey })).sessionId
        } catch {
            res.status(401).json({ error: 'invalid_token' })
            return
        }
        const session = await deps.queue.get(sessionId)
        if (!session || session.state !== 'running') {
            deps.log.warn({ session_id: sessionId, state: session?.state ?? null }, 'inference_denied_session_not_live')
            res.status(403).json({ error: 'session_not_live' })
            return
        }
        next()
    })

    const forward = asyncHandler(async (req: Request, res: Response): Promise<void> => {
        const headers: Record<string, string> = { authorization: `Bearer ${deps.gatewayKey}` }
        for (const name of FORWARD_REQUEST_HEADERS) {
            const value = req.headers[name]
            if (typeof value === 'string') {
                headers[name] = value
            }
        }
        const body = req.method === 'POST' && Buffer.isBuffer(req.body) && req.body.length > 0 ? req.body : undefined
        const upstream = await deps.http.fetch(`${gatewayRoot}${req.path}`, {
            method: req.method,
            headers,
            body,
            signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
        })

        res.status(upstream.status)
        const contentType = upstream.headers.get('content-type')
        if (contentType) {
            res.setHeader('content-type', contentType)
        }
        if (!upstream.body) {
            res.end()
            return
        }
        // Pipe the gateway stream straight through — SSE token deltas reach
        // the sandbox as they arrive.
        await new Promise<void>((resolve, reject) => {
            const stream = Readable.fromWeb(upstream.body as unknown as WebReadableStream)
            stream.on('error', reject)
            res.on('close', resolve)
            stream.pipe(res)
            stream.on('end', resolve)
        })
    })

    for (const route of ALLOWED) {
        if (route.method === 'GET') {
            router.get(route.path, authenticate, forward)
        } else {
            router.post(route.path, authenticate, forward)
        }
    }
    return router
}
