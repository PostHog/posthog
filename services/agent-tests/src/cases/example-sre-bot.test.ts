/**
 * Example bundle e2e — `services/agent-tests/src/examples/sre-slack-bot/`.
 *
 * Loads the bundle from disk, deploys it through the harness, and
 * drives a realistic alert flow with the faux model. The point is
 * a regression net: if the bundle's spec.json or skill paths drift
 * out of sync with what the runner / tool registry expect, this
 * case fails before the bundle reaches production.
 *
 * NOT a real-inference test — the model is faux; the assertions
 * are about wiring, not about whether the agent's prose is good.
 */

import { readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BUNDLE_ROOT = resolve(__dirname, '../examples/sre-slack-bot')
const BUNDLE_FILES = ['agent.md', 'skills/triage-playbook/SKILL.md', 'skills/slack-thread-protocol/SKILL.md'] as const

async function loadBundle(): Promise<{ spec: Record<string, unknown>; files: Record<string, string> }> {
    const spec = JSON.parse(await readFile(join(BUNDLE_ROOT, 'spec.json'), 'utf-8')) as Record<string, unknown>
    const files: Record<string, string> = {}
    for (const path of BUNDLE_FILES) {
        files[path] = await readFile(join(BUNDLE_ROOT, path), 'utf-8')
    }
    return { spec, files }
}

/** Stub fetch — covers slack.com/api/* and any web-fetch URL. */
function stubFetch(responses: Record<string, unknown>): typeof fetch {
    return (async (input: string | URL | Request) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
        const match = Object.keys(responses).find((k) => url.includes(k))
        const body = match ? responses[match] : { ok: true }
        return {
            ok: true,
            status: 200,
            json: async () => body,
            text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
        } as unknown as Response
    }) as unknown as typeof fetch
}

describe('example: sre-slack-bot bundle', () => {
    let c: Cluster
    const originalFetch = global.fetch

    beforeEach(async () => {
        c = await buildCluster({
            // Slack tools resolve credentials from session integrations; the
            // tools throw if no token is wired even when fetch is stubbed.
            resolveIntegrations: async () => ({
                'slack:T01TEST': { kind: 'slack', access_token: 'xoxb-faux' },
            }),
        })
    })

    afterEach(async () => {
        global.fetch = originalFetch
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('loads cleanly — spec parses, all 3 bundle files are present', async () => {
        const { spec, files } = await loadBundle()
        // Sanity: every skill path referenced in spec.skills[] is also a file
        // we shipped. Drift between the two is the most common bundle bug.
        const skillPaths = (spec.skills as Array<{ path: string }>).map((s) => s.path)
        for (const p of skillPaths) {
            expect(files[p]).not.toBeUndefined()
        }
        // agent.md is the default entrypoint and must exist.
        expect(files['agent.md']).not.toBeUndefined()
        expect(files['agent.md'].length).toBeGreaterThan(200)
    })

    it('deploys end-to-end and runs through a webhook-driven triage flow', async () => {
        const { spec, files } = await loadBundle()

        global.fetch = stubFetch({
            'slack.com/api/reactions.add': { ok: true },
            'slack.com/api/conversations.history': {
                ok: true,
                messages: [{ ts: '1700000000.000100', user: 'U01', text: 'anyone else seeing 500s on ingest?' }],
                has_more: false,
            },
            'slack.com/api/chat.postMessage': { ok: true, ts: '1700000050.000200', channel: 'C01' },
            'runbooks.internal/ingestion-500s': '# Runbook: ingest 500s\nCheck kafka consumer lag.',
        })

        // The faux model's script — a realistic six-call investigation.
        c.setScript([
            // Phase 1: load the skill before doing anything.
            fauxCallTool('@posthog/load-skill', { id: 'triage-playbook' }),
            // Phase 2: react to acknowledge.
            fauxCallTool('@posthog/slack-react', {
                team_integration_id: 'slack:T01TEST',
                channel: 'C-incidents',
                ts: '1700000099.000000',
                name: 'eyes',
            }),
            // Phase 3: read the channel for context.
            fauxCallTool('@posthog/slack-read-channel', {
                team_integration_id: 'slack:T01TEST',
                channel: 'C-incidents',
                limit: 20,
            }),
            // Phase 4: fetch the runbook.
            fauxCallTool('@posthog/web-fetch', {
                url: 'https://runbooks.internal/ingestion-500s',
            }),
            // Phase 5: load the reply-protocol skill.
            fauxCallTool('@posthog/load-skill', { id: 'slack-thread-protocol' }),
            // Phase 6: post the final analysis.
            fauxCallTool('@posthog/slack-post-message', {
                team_integration_id: 'slack:T01TEST',
                channel: 'C-incidents',
                thread_ts: '1700000099.000000',
                text: ':mag: *TL;DR:* ingest 500s correlate with kafka consumer lag.\n\n*Suggested next step* cc oncall',
            }),
            // Close the turn.
            fauxText('Triage posted, ending session.'),
        ])

        await c.deployAgent({ slug: 'sre-slack-bot', spec, files })
        const alertPayload = {
            alerts: [
                {
                    labels: { alertname: 'Ingestion500s', severity: 'critical' },
                    annotations: { runbook_url: 'https://runbooks.internal/ingestion-500s' },
                    startsAt: '2026-05-29T14:32:00Z',
                    value: '4.7',
                },
            ],
        }
        const res = await request(c.ingress).post('/agents/sre-slack-bot/webhook').send(alertPayload)
        expect(res.status).toBe(200)
        await c.drain({ iterations: 100 })

        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')

        const calledTools = session!.conversation
            .filter((m) => m.role === 'toolResult')
            .map((m) => (m as { toolName?: string }).toolName)
        expect(calledTools).toEqual([
            '@posthog/load-skill',
            '@posthog/slack-react',
            '@posthog/slack-read-channel',
            '@posthog/web-fetch',
            '@posthog/load-skill',
            '@posthog/slack-post-message',
        ])
    })
})
