/**
 * Inference proxy route tests — real PG session queue (liveness checks run
 * against the actual session row), real Express app via `buildApp`, and a
 * local fake upstream standing in for the ai-gateway (the model layer is the
 * one thing we always fake). Covers the §8 properties: token-gated, session
 * liveness enforced, the real gateway key attached upstream and never
 * required in the caller, streaming pass-through, allowlisted paths only.
 */

import { randomUUID } from 'node:crypto'
import * as http from 'node:http'
import { AddressInfo } from 'node:net'
import { Pool } from 'pg'
import request from 'supertest'

import {
    DirectHttpClient,
    EMPTY_USAGE_TOTAL,
    mintInferenceProxyToken,
    PgCredentialBroker,
    PgRevisionStore,
    PgSessionQueue,
    RedisSessionEventBus,
} from '@posthog/agent-shared'
import type { AgentSession } from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import { buildApp } from './server'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
// nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
const REDIS_URL = process.env.REDIS_URL ?? 'redis://localhost:6379'
const SIGNING_KEY = 'test-internal-signing-key'
const GATEWAY_KEY = 'phc_real_gateway_key'

interface UpstreamCapture {
    method: string
    url: string
    authorization?: string
    xApiKey?: string
    body: string
}

/** Fake ai-gateway: records each request, answers /v1/models with JSON and /v1/messages with SSE. */
function startFakeGateway(): Promise<{ url: string; captures: UpstreamCapture[]; close: () => Promise<void> }> {
    const captures: UpstreamCapture[] = []
    const server = http.createServer((req, res) => {
        const chunks: Buffer[] = []
        req.on('data', (c) => chunks.push(c))
        req.on('end', () => {
            captures.push({
                method: req.method ?? '',
                url: req.url ?? '',
                authorization: req.headers.authorization,
                xApiKey: req.headers['x-api-key'] as string | undefined,
                body: Buffer.concat(chunks).toString('utf-8'),
            })
            if (req.url === '/v1/models') {
                res.writeHead(200, { 'content-type': 'application/json' })
                res.end(JSON.stringify({ data: [{ id: 'claude-sonnet-4-6', context_window: 200000 }] }))
                return
            }
            if (req.url === '/v1/messages') {
                res.writeHead(200, { 'content-type': 'text/event-stream' })
                res.write('event: message_start\ndata: {"type":"message_start"}\n\n')
                res.write('event: message_stop\ndata: {"type":"message_stop"}\n\n')
                res.end()
                return
            }
            res.writeHead(500)
            res.end('unexpected upstream path')
        })
    })
    return new Promise((resolve) => {
        server.listen(0, '127.0.0.1', () => {
            const { port } = server.address() as AddressInfo
            resolve({
                url: `http://127.0.0.1:${port}`,
                captures,
                close: () => new Promise((r) => server.close(() => r())),
            })
        })
    })
}

function session(id: string, state: string): AgentSession {
    return {
        id,
        application_id: '00000000-0000-0000-0000-000000000001',
        revision_id: '00000000-0000-0000-0000-000000000002',
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: null,
        state,
        conversation: [{ role: 'user', content: 'go', timestamp: 1 }],
        pending_inputs: [],
        principal: null,
        retry_count: 0,
        usage_total: { ...EMPTY_USAGE_TOTAL },
        acl: [],
        pending_elevation_requests: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    } as unknown as AgentSession
}

describe('inference proxy route', () => {
    let pool: Pool
    let bus: RedisSessionEventBus
    let queue: PgSessionQueue
    let gateway: Awaited<ReturnType<typeof startFakeGateway>>
    let app: ReturnType<typeof buildApp>

    beforeAll(async () => {
        pool = new Pool({ connectionString: TEST_DB_URL })
        bus = new RedisSessionEventBus({
            url: REDIS_URL,
            channelPrefix: `inference_proxy_test_${Math.random().toString(36).slice(2, 10)}`,
        })
        await bus.connect()
        gateway = await startFakeGateway()
    })

    beforeEach(async () => {
        await reset({ databaseUrl: TEST_DB_URL })
        queue = new PgSessionQueue(pool)
        gateway.captures.length = 0
        app = buildApp({
            revisions: new PgRevisionStore(pool),
            queue,
            bus,
            credentialBroker: new PgCredentialBroker(pool, {
                encryptionSaltKeys: '01234567890123456789012345678901',
            }),
            teamId: 1,
            routingMode: 'path',
            pathPrefix: '/agents',
            inferenceProxy: {
                signingKey: SIGNING_KEY,
                gatewayUrl: gateway.url,
                gatewayKey: GATEWAY_KEY,
                http: new DirectHttpClient(),
            },
        })
    })

    afterAll(async () => {
        await gateway.close()
        await bus.disconnect()
        await pool.end()
    })

    async function liveToken(id = randomUUID()): Promise<string> {
        await queue.enqueue(session(id, 'queued'))
        await queue.update(id, { state: 'running' })
        return mintInferenceProxyToken({ sessionId: id, signingKey: SIGNING_KEY, ttlSec: 60 })
    }

    it('rejects a request without a token', async () => {
        const res = await request(app).get('/inference/v1/models')
        expect(res.status).toBe(401)
        expect(gateway.captures).toHaveLength(0)
    })

    it('rejects a garbage token', async () => {
        const res = await request(app).get('/inference/v1/models').set('Authorization', 'Bearer not-a-jwt')
        expect(res.status).toBe(401)
        expect(gateway.captures).toHaveLength(0)
    })

    it('rejects a valid token whose session is not running (kill switch)', async () => {
        const id = randomUUID()
        await queue.enqueue(session(id, 'queued'))
        await queue.update(id, { state: 'completed' })
        const token = await mintInferenceProxyToken({ sessionId: id, signingKey: SIGNING_KEY, ttlSec: 60 })
        const res = await request(app).get('/inference/v1/models').set('Authorization', `Bearer ${token}`)
        expect(res.status).toBe(403)
        expect(res.body.error).toBe('session_not_live')
        expect(gateway.captures).toHaveLength(0)
    })

    it('rejects a valid token for a session that does not exist', async () => {
        const token = await mintInferenceProxyToken({ sessionId: randomUUID(), signingKey: SIGNING_KEY, ttlSec: 60 })
        const res = await request(app).get('/inference/v1/models').set('Authorization', `Bearer ${token}`)
        expect(res.status).toBe(403)
        expect(gateway.captures).toHaveLength(0)
    })

    it('forwards GET /v1/models with the real gateway key swapped in', async () => {
        const token = await liveToken()
        const res = await request(app).get('/inference/v1/models').set('Authorization', `Bearer ${token}`)
        expect(res.status).toBe(200)
        expect(res.body.data[0]).toMatchObject({ id: 'claude-sonnet-4-6', context_window: 200000 })

        expect(gateway.captures).toHaveLength(1)
        const upstream = gateway.captures[0]
        expect(upstream.url).toBe('/v1/models')
        // The real credential is attached proxy-side; the session token never travels upstream.
        expect(upstream.authorization).toBe(`Bearer ${GATEWAY_KEY}`)
        expect(upstream.xApiKey).toBeUndefined()
    })

    it('accepts the token via x-api-key (Anthropic SDK header)', async () => {
        const token = await liveToken()
        const res = await request(app).get('/inference/v1/models').set('x-api-key', token)
        expect(res.status).toBe(200)
    })

    it('streams POST /v1/messages through, body verbatim', async () => {
        const token = await liveToken()
        const body = { model: 'claude-sonnet-4-6', max_tokens: 64, messages: [{ role: 'user', content: 'hi' }] }
        const res = await request(app)
            .post('/inference/v1/messages')
            .set('Authorization', `Bearer ${token}`)
            .set('Content-Type', 'application/json')
            .send(body)
        expect(res.status).toBe(200)
        expect(res.headers['content-type']).toContain('text/event-stream')
        expect(res.text).toContain('message_start')
        expect(res.text).toContain('message_stop')

        const upstream = gateway.captures[0]
        expect(upstream.method).toBe('POST')
        expect(JSON.parse(upstream.body)).toEqual(body)
        expect(upstream.authorization).toBe(`Bearer ${GATEWAY_KEY}`)
    })

    it('404s non-allowlisted upstream paths', async () => {
        const token = await liveToken()
        const res = await request(app).post('/inference/v1/admin/keys').set('Authorization', `Bearer ${token}`)
        expect(res.status).toBe(404)
        expect(gateway.captures).toHaveLength(0)
    })
})
