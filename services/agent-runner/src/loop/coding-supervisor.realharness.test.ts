/**
 * Full e2e against the REAL harness. Drives `runCodingSession` — the actual
 * supervisor + Docker pool — against the published PostHog Code image
 * (`agent-server`), with a live model via the local ai-gateway. Proves the
 * whole tier-1 → tier-2 path: JWT auth, SSE session, ACP event parsing, real
 * tool execution, to completion.
 *
 * Opt-in — skipped unless all of: docker is up, the published image is
 * present, and the local ai-gateway answers on :8080 (and serves the model on
 * /v1/messages with `context_window` on /v1/models). Build/pull:
 *   docker pull ghcr.io/posthog/posthog-sandbox-base:master
 *   (and run the ai-gateway locally — bin/start-ai-gateway)
 */

import { execFile } from 'node:child_process'
import * as http from 'node:http'
import { promisify } from 'node:util'
import { describe, expect, it } from 'vitest'

import {
    buildResumePrompt,
    CodingEvent,
    CodingLaunchConfig,
    ConversationMessage,
    DockerCodingSandboxPool,
    formatConversationForResume,
    PUBLISHED_HARNESS_IMAGE,
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

function launch(overrides: Partial<CodingLaunchConfig> = {}): CodingLaunchConfig {
    return {
        model: MODEL,
        // The pool rewrites localhost → host.docker.internal for the container.
        modelBaseUrl: GATEWAY,
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
        const pool = new DockerCodingSandboxPool({ image: PUBLISHED_HARNESS_IMAGE })
        const events: CodingEvent[] = []

        const result = await runCodingSession(
            {
                sessionId: `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
                teamId: 1,
                launch: launch(),
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
    }, 300_000)

    it('a resume-wrapped first message gives a fresh harness the prior conversation context', async () => {
        // Mirrors what driveCodingSession does on a /send re-claim: the
        // prior conversation is replayed as context around the new message,
        // and the cold harness must answer from it.
        const prior: ConversationMessage[] = [
            {
                role: 'user',
                content: 'Remember this deploy codeword for later: XYZZY-PLUGH. Just confirm you have it.',
                timestamp: 1,
            },
            {
                role: 'assistant',
                content: [{ type: 'text', text: 'Confirmed — the deploy codeword is XYZZY-PLUGH.' }],
                timestamp: 2,
            },
        ]
        const history = formatConversationForResume(prior)
        expect(history).not.toBeNull()

        const pool = new DockerCodingSandboxPool({ image: PUBLISHED_HARNESS_IMAGE })
        const result = await runCodingSession(
            {
                sessionId: `e2e-resume-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
                teamId: 1,
                launch: launch(),
                userMessage: buildResumePrompt(
                    history!,
                    'What was the deploy codeword from earlier? Reply with exactly that codeword and nothing else.'
                ),
                timeoutMs: 240_000,
            },
            {
                pool,
                approve: async (): Promise<ApprovalDecision> => ({ optionId: 'allow' }),
            }
        )

        expect(result.state, `events: ${JSON.stringify(result.events.slice(-8))}`).toBe('completed')
        // The fresh harness answered from the replayed history.
        expect(result.assistantText.join('')).toContain('XYZZY-PLUGH')
    }, 300_000)
})

if (!READY) {
    // eslint-disable-next-line no-console
    console.warn(
        `[coding-supervisor.realharness] e2e skipped: need docker + image ${PUBLISHED_HARNESS_IMAGE} + local ai-gateway on ${GATEWAY}.`
    )
}
