/**
 * Coding agent through the REAL inference proxy — the full §8 wiring, live:
 * a real Worker claims the session, the driver mints a session capability
 * token, a real Docker harness boots and sends its model calls to the
 * cluster's real ingress `/inference/v1/*`, which swaps in the gateway key
 * and forwards to the local ai-gateway. The real gateway credential never
 * enters the sandbox.
 *
 * Opt-in like the other realharness suite — skipped unless docker has the
 * published image and the local ai-gateway answers on :8080
 * (bin/start-ai-gateway).
 */

import { execFile } from 'node:child_process'
import * as http from 'node:http'
import { AddressInfo } from 'node:net'
import { promisify } from 'node:util'
import request from 'supertest'
import { afterAll, afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
    DirectHttpClient,
    DockerCodingSandboxPool,
    mintInferenceProxyToken,
    PUBLISHED_HARNESS_IMAGE,
} from '@posthog/agent-shared'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

const exec = promisify(execFile)
const GATEWAY = process.env.LOCAL_AI_GATEWAY ?? 'http://127.0.0.1:8080'
const MODEL = process.env.CODING_MODEL ?? 'claude-sonnet-4-6'
const SIGNING_KEY = 'realharness-internal-signing-key'

async function preconditionsMet(): Promise<boolean> {
    try {
        await exec('docker', ['image', 'inspect', PUBLISHED_HARNESS_IMAGE], { timeout: 5_000 })
    } catch {
        return false
    }
    return new Promise((resolve) => {
        const u = new URL(`${GATEWAY}/v1/models`)
        const req = http.get({ hostname: u.hostname, port: u.port, path: u.pathname, timeout: 3_000 }, (res) => {
            res.resume()
            resolve(res.statusCode === 200)
        })
        req.on('error', () => resolve(false))
        req.on('timeout', () => {
            req.destroy()
            resolve(false)
        })
    })
}

const READY = await preconditionsMet()
const maybe = READY ? describe : describe.skip

maybe('coding agent via inference proxy: real harness e2e', () => {
    let c: Cluster
    // The sandbox needs a real listening endpoint for the ingress app; the
    // handler is late-bound so the port is known before the cluster (and its
    // proxy-base config) is built.
    let server: http.Server
    let proxyBase: string
    let handler: http.RequestListener = (_req, res) => res.writeHead(503).end()

    beforeEach(async () => {
        server = http.createServer((req, res) => handler(req, res))
        await new Promise<void>((r) => server.listen(0, '127.0.0.1', r))
        const { port } = server.address() as AddressInfo
        proxyBase = `http://127.0.0.1:${port}/inference`

        c = await buildCluster({
            codingPool: new DockerCodingSandboxPool({ image: PUBLISHED_HARNESS_IMAGE }),
            // The driver mints the session token; the harness reaches the
            // model only via the proxy. No apiKey here — the real credential
            // lives exclusively on the ingress side below.
            codingGateway: { baseUrl: proxyBase, projectId: 1, inferenceProxy: { signingKey: SIGNING_KEY } },
            inferenceProxy: {
                signingKey: SIGNING_KEY,
                gatewayUrl: GATEWAY,
                gatewayKey: 'phx_local',
                http: new DirectHttpClient(),
            },
        })
        handler = c.ingress
    })
    afterEach(async () => {
        await c.teardown()
        await new Promise<void>((r) => server.close(() => r()))
    })
    afterAll(async () => {
        await closeSharedPool()
    })

    it('runs a real coding turn with only a session token in the sandbox; the token dies with the session', async () => {
        await c.deployAgent({
            slug: 'coder-proxy',
            spec: {
                model: MODEL,
                sandbox: { trust_profile: 'coding-write', loop_location: 'in_sandbox' },
            },
            files: { 'agent.md': 'You are a concise coding agent.' },
        })

        const run = await request(c.ingress)
            .post('/agents/coder-proxy/run')
            .send({ message: 'Run the shell command `echo proxy-roundtrip-ok` and report its output.' })
        const sessionId = run.body.session_id as string
        await c.drain({ iterations: 30 })

        const session = await c.queue.get(sessionId)
        expect(session!.state).toBe('completed')
        // Usage accrued → the model was reached through proxy → gateway.
        expect(session!.usage_total!.tokens_out).toBeGreaterThan(0)
        const assistant = session!.conversation.find((m) => m.role === 'assistant')
        expect(assistant).toBeTruthy()

        // Kill switch: the session is no longer live, so even a freshly
        // minted token for it gets 403 — inference stops with the session.
        const deadToken = await mintInferenceProxyToken({ sessionId, signingKey: SIGNING_KEY, ttlSec: 60 })
        const denied = await request(c.ingress).get('/inference/v1/models').set('Authorization', `Bearer ${deadToken}`)
        expect(denied.status).toBe(403)
        expect(denied.body.error).toBe('session_not_live')
    }, 300_000)
})

if (!READY) {
    // eslint-disable-next-line no-console
    console.warn(
        `[coding-inference-proxy.realharness] e2e skipped: need docker + image ${PUBLISHED_HARNESS_IMAGE} + local ai-gateway on ${GATEWAY}.`
    )
}
