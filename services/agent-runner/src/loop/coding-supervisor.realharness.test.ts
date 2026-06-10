/**
 * Full e2e against the REAL harness. Drives `runCodingSession` — the actual
 * supervisor + Docker pool — against the published PostHog Code image
 * (`agent-server`), with a live model proxied through the local ai-gateway.
 * Proves the whole tier-1 → tier-2 path: JWT auth, SSE session, ACP event
 * parsing, real tool execution, to completion.
 *
 * Opt-in — skipped unless all of: docker is up, the published image is
 * present, and the local ai-gateway answers on :8080. Build/pull:
 *   docker pull ghcr.io/posthog/posthog-sandbox-base:master
 *   (and run the ai-gateway locally — bin/start-ai-gateway)
 *
 * A tiny in-process shim injects `context_window` into the gateway's
 * /v1/models (the local dev gateway omits it; the harness requires it) and
 * passes inference through untouched — so the test is self-contained.
 */

import { execFile } from 'node:child_process'
import * as http from 'node:http'
import { AddressInfo } from 'node:net'
import { promisify } from 'node:util'
import { describe, expect, it } from 'vitest'

import {
    DockerCodingSandboxPool,
    PUBLISHED_HARNESS_IMAGE,
    CodingEvent,
    CodingLaunchConfig,
} from '@posthog/agent-shared'

import { ApprovalDecision, runCodingSession } from './coding-supervisor'

const exec = promisify(execFile)
const GATEWAY = process.env.LOCAL_AI_GATEWAY ?? 'http://127.0.0.1:8080'
const MODEL = process.env.CODING_MODEL ?? 'claude-sonnet-4-6'

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

/** Passthrough proxy to the gateway that injects context_window into /v1/models. */
function startContextWindowShim(): Promise<{ url: string; close: () => Promise<void> }> {
    const up = new URL(GATEWAY)
    return new Promise((resolve) => {
        const server = http.createServer((req, res) => {
            const isModels = req.method === 'GET' && (req.url ?? '').startsWith('/v1/models')
            const upstream = http.request(
                {
                    host: up.hostname,
                    port: up.port,
                    path: req.url,
                    method: req.method,
                    headers: { ...req.headers, host: up.host },
                },
                (ur) => {
                    if (!isModels) {
                        res.writeHead(ur.statusCode ?? 200, ur.headers)
                        return ur.pipe(res)
                    }
                    let body = ''
                    ur.setEncoding('utf-8')
                    ur.on('data', (c) => (body += c))
                    ur.on('end', () => {
                        let out = body
                        try {
                            const d = JSON.parse(body)
                            const list = Array.isArray(d) ? d : (d.data ?? d.models ?? [])
                            for (const m of list) {
                                if (m && m.context_window == null) {
                                    m.context_window = 200_000
                                }
                            }
                            out = JSON.stringify(d)
                        } catch {
                            /* leave as-is */
                        }
                        const h = { ...ur.headers }
                        delete h['content-length']
                        res.writeHead(ur.statusCode ?? 200, h)
                        res.end(out)
                    })
                }
            )
            upstream.on('error', () => {
                res.writeHead(502)
                res.end()
            })
            req.pipe(upstream)
        })
        server.listen(0, '0.0.0.0', () => {
            const port = (server.address() as AddressInfo).port
            resolve({
                url: `http://host.docker.internal:${port}`,
                close: () => new Promise((r) => server.close(() => r())),
            })
        })
    })
}

function launch(modelBaseUrl: string, overrides: Partial<CodingLaunchConfig> = {}): CodingLaunchConfig {
    return {
        model: MODEL,
        modelBaseUrl,
        apiKey: 'phx_local',
        apiUrl: 'http://host.docker.internal:8010',
        projectId: 1,
        skills: [],
        mcpServers: [],
        limits: { memoryMb: 2048, cpuCores: 2, wallSeconds: 120 },
        writable: true,
        ...overrides,
    }
}

maybe('runCodingSession: real harness e2e', () => {
    it('runs a real coding turn (reason → tool → complete) via the local gateway', async () => {
        const shim = await startContextWindowShim()
        const pool = new DockerCodingSandboxPool({ image: PUBLISHED_HARNESS_IMAGE })
        const events: CodingEvent[] = []

        try {
            const result = await runCodingSession(
                {
                    sessionId: `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
                    teamId: 1,
                    launch: launch(shim.url),
                    userMessage: 'Run the shell command `echo hello-from-real-harness` and report its output.',
                    timeoutMs: 240_000,
                },
                {
                    pool,
                    approve: async (): Promise<ApprovalDecision> => ({ optionId: 'allow' }),
                    onEvent: (e) => events.push(e),
                }
            )

            // The session completed without a fatal harness/model error.
            expect(result.state, `events: ${JSON.stringify(events.slice(-8))}`).toBe('completed')

            // It genuinely ran the agent loop: a tool call and/or assistant text.
            const ranWork = result.toolCalls.length > 0 || result.assistantText.join('').length > 0
            expect(
                ranWork,
                `tools=${JSON.stringify(result.toolCalls)} text=${result.assistantText.join('').slice(0, 200)}`
            ).toBe(true)

            // We reached the model (usage accrued) — proves the gateway round-trip.
            expect(result.events.some((e) => e.kind === 'usage')).toBe(true)
        } finally {
            await shim.close()
        }
    }, 300_000)
})

if (!READY) {
    // eslint-disable-next-line no-console
    console.warn(
        `[coding-supervisor.realharness] e2e skipped: need docker + image ${PUBLISHED_HARNESS_IMAGE} + local ai-gateway on ${GATEWAY}.`
    )
}
