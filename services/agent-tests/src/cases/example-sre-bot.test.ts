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

import { buildCluster, closeSharedPool, Cluster, fakeAuthProvider, fauxCallTool, fauxText } from '../harness'

const WEBHOOK_SECRET = 'sre-test-webhook-secret'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BUNDLE_ROOT = resolve(__dirname, '../examples/sre-slack-bot')
const BUNDLE_FILES = [
    'agent.md',
    'skills/triage-playbook/SKILL.md',
    'skills/slack-thread-protocol/SKILL.md',
    'skills/incident-io-playbook/SKILL.md',
] as const

async function loadBundle(): Promise<{ spec: Record<string, unknown>; files: Record<string, string> }> {
    const spec = JSON.parse(await readFile(join(BUNDLE_ROOT, 'spec.json'), 'utf-8')) as Record<string, unknown>
    const files: Record<string, string> = {}
    for (const path of BUNDLE_FILES) {
        files[path] = await readFile(join(BUNDLE_ROOT, path), 'utf-8')
    }
    return { spec, files }
}

describe('example: sre-slack-bot bundle', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster({
            // Bundle uses bring-your-own Slack via `@posthog/http-request` +
            // a `SLACK_BOT_TOKEN` secret — the runner substitutes the value
            // into `Authorization: Bearer ${SLACK_BOT_TOKEN}` before dispatch.
            // No platform-managed Slack integration is needed.
            resolveSecrets: async () => ({
                SLACK_BOT_TOKEN: 'xoxb-test-token',
                SLACK_SIGNING_SECRET: 'test-signing-secret',
                INCIDENT_IO_TOKEN: 'inc_test_token',
            }),
            authProvider: fakeAuthProvider({ shared: WEBHOOK_SECRET }),
        })
    })

    afterEach(async () => {
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

    it('deploys end-to-end and runs through a webhook-driven triage flow using bring-your-own Slack token', async () => {
        const { spec, files } = await loadBundle()

        // Track every Slack-bound request the agent made so we can prove the
        // bearer header was stamped (i.e. ${SLACK_BOT_TOKEN} substitution
        // actually fired on the runner side) and the JSON body was shaped
        // correctly for the Slack Web API. The recorder replaces the runner's
        // HttpClient — bare global.fetch wouldn't intercept anymore now that
        // tools dispatch through `ctx.http.fetch`.
        const slackCalls: Array<{ url: string; method?: string; auth?: string; body?: unknown }> = []
        const incidentCalls: Array<{ url: string; method?: string; auth?: string; body?: unknown }> = []
        const recorderHttp = {
            fetch: (input: string | URL, init?: RequestInit): Promise<Response> => {
                const url = typeof input === 'string' ? input : input.toString()
                if (url.includes('slack.com/api/')) {
                    const headers = (init?.headers ?? {}) as Record<string, string>
                    slackCalls.push({
                        url,
                        method: init?.method,
                        auth: headers.Authorization,
                        body: typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body,
                    })
                    return Promise.resolve({
                        ok: true,
                        status: 200,
                        json: async () => ({ ok: true, ts: '1700000050.000200', channel: 'C01' }),
                        text: async () => JSON.stringify({ ok: true, ts: '1700000050.000200', channel: 'C01' }),
                        headers: new Map([['content-type', 'application/json']]),
                    } as unknown as Response)
                }
                if (url.includes('api.incident.io/')) {
                    const headers = (init?.headers ?? {}) as Record<string, string>
                    incidentCalls.push({
                        url,
                        method: init?.method,
                        auth: headers.Authorization,
                        body: typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body,
                    })
                    // Shape mirrors incident.io's POST .../updates response.
                    return Promise.resolve({
                        ok: true,
                        status: 200,
                        json: async () => ({
                            incident_update: { id: 'IU_01', incident_id: '01HXYZ', message: 'triage posted' },
                        }),
                        text: async () =>
                            JSON.stringify({
                                incident_update: { id: 'IU_01', incident_id: '01HXYZ', message: 'triage posted' },
                            }),
                        headers: new Map([['content-type', 'application/json']]),
                    } as unknown as Response)
                }
                if (url.includes('runbooks.internal')) {
                    return Promise.resolve({
                        ok: true,
                        status: 200,
                        text: async () => '# Runbook: ingest 500s\nCheck kafka consumer lag.',
                        headers: new Map([['content-type', 'text/markdown']]),
                    } as unknown as Response)
                }
                return Promise.resolve({
                    ok: true,
                    status: 200,
                    text: async () => '{}',
                    headers: new Map(),
                } as unknown as Response)
            },
        }
        // Rebuild the cluster with the http recorder. The default cluster
        // (from beforeEach) carries the real HttpClient; we tear it down and
        // start fresh so the runner threads the recorder into ToolContext.http.
        await c.teardown()
        c = await buildCluster({
            resolveSecrets: async () => ({
                SLACK_BOT_TOKEN: 'xoxb-test-token',
                SLACK_SIGNING_SECRET: 'test-signing-secret',
                INCIDENT_IO_TOKEN: 'inc_test_token',
            }),
            authProvider: fakeAuthProvider({ shared: WEBHOOK_SECRET }),
            http: recorderHttp,
        })

        // The faux model's script — same triage flow as before, but every
        // Slack tool call now goes through `@posthog/http-request` against
        // `https://slack.com/api/<method>` with `${SLACK_BOT_TOKEN}` in the
        // Authorization header. The runner substitutes the secret before
        // dispatch, so the raw header here is the placeholder; the captured
        // fetch headers above prove the substitution fired.
        c.setScript([
            // Phase 1: react to acknowledge.
            fauxCallTool('@posthog/http-request', {
                url: 'https://slack.com/api/reactions.add',
                method: 'POST',
                headers: { Authorization: 'Bearer ${SLACK_BOT_TOKEN}' },
                body: { channel: 'C-incidents', timestamp: '1700000099.000000', name: 'eyes' },
            }),
            // Phase 2: check prior incidents for this alert signature.
            fauxCallTool('@posthog/table-query', {
                table: 'incidents',
                where: { alert_signature: 'ingestion-500s' },
                limit: 5,
            }),
            // Phase 2b: load the incident.io playbook then check for an
            // active incident covering this signature. Proves the
            // ${INCIDENT_IO_TOKEN} substitution wires up the same way
            // ${SLACK_BOT_TOKEN} does.
            fauxCallTool('@posthog/load-skill', { id: 'incident-io-playbook' }),
            fauxCallTool('@posthog/http-request', {
                url: 'https://api.incident.io/v2/incidents?status_category%5Bone_of%5D=active&page_size=25',
                method: 'GET',
                headers: { Authorization: 'Bearer ${INCIDENT_IO_TOKEN}' },
            }),
            // Phase 3: load the triage skill.
            fauxCallTool('@posthog/load-skill', { id: 'triage-playbook' }),
            // Phase 4: read the channel for context.
            fauxCallTool('@posthog/http-request', {
                url: 'https://slack.com/api/conversations.history',
                method: 'POST',
                headers: { Authorization: 'Bearer ${SLACK_BOT_TOKEN}' },
                body: { channel: 'C-incidents', limit: 20 },
            }),
            // Phase 5: fetch the runbook.
            fauxCallTool('@posthog/web-fetch', {
                url: 'https://runbooks.internal/ingestion-500s',
            }),
            // Phase 6: load the reply-protocol skill.
            fauxCallTool('@posthog/load-skill', { id: 'slack-thread-protocol' }),
            // Phase 7: post the final analysis.
            fauxCallTool('@posthog/http-request', {
                url: 'https://slack.com/api/chat.postMessage',
                method: 'POST',
                headers: { Authorization: 'Bearer ${SLACK_BOT_TOKEN}' },
                body: {
                    channel: 'C-incidents',
                    thread_ts: '1700000099.000000',
                    text: ':mag: *TL;DR:* ingest 500s correlate with kafka consumer lag.\n\n*Suggested next step* cc oncall',
                },
            }),
            // Phase 8a: record the resolved outcome so future alerts can
            // short-circuit. Dedupe on thread_url.
            fauxCallTool('@posthog/table-append', {
                table: 'incidents',
                rows: [
                    {
                        alert_signature: 'ingestion-500s',
                        symptom: 'ingest 500s spike',
                        root_cause: 'kafka consumer lag',
                        mitigation: 'scaled consumer group, lag drained in 4m',
                        thread_url: 'https://slack.com/archives/C-incidents/p1700000099000000',
                        resolved_at: '2026-05-29T15:10:00Z',
                        incident_io_id: '01HXYZ',
                    },
                ],
                dedupe_on: 'thread_url',
            }),
            // Phase 8b: post the final summary onto the incident.io
            // timeline so the post-mortem record matches Slack.
            fauxCallTool('@posthog/http-request', {
                url: 'https://api.incident.io/v2/incidents/01HXYZ/updates',
                method: 'POST',
                headers: { Authorization: 'Bearer ${INCIDENT_IO_TOKEN}' },
                body: {
                    incident_id: '01HXYZ',
                    message:
                        '*Resolved.* Root cause: kafka consumer-group `events-main` under-provisioned after morning deploy. Mitigation: scaled 12→18 pods; lag drained in 4m.',
                },
            }),
            // Close the turn.
            fauxText('Triage posted, outcome recorded, ending session.'),
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
        // The example bundle's webhook is gated by spec.auth.modes — the
        // shared_secret mode expects the value in the `X-Webhook-Secret`
        // header. Production callers (incident.io webhook config, Grafana
        // alertmanager headers, …) set this verbatim.
        const res = await request(c.ingress)
            .post('/agents/sre-slack-bot/webhook')
            .set('x-webhook-secret', WEBHOOK_SECRET)
            .send(alertPayload)
        expect(res.status).toBe(200)
        await c.drain({ iterations: 100 })

        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')

        const calledTools = session!.conversation
            .filter((m) => m.role === 'toolResult')
            .map((m) => (m as { toolName?: string }).toolName)
        expect(calledTools).toEqual([
            '@posthog/http-request', // reactions.add (slack)
            '@posthog/table-query',
            '@posthog/load-skill', // incident-io-playbook
            '@posthog/http-request', // list active incidents (incident.io)
            '@posthog/load-skill', // triage-playbook
            '@posthog/http-request', // conversations.history (slack)
            '@posthog/web-fetch',
            '@posthog/load-skill', // slack-thread-protocol
            '@posthog/http-request', // chat.postMessage (slack)
            '@posthog/table-append',
            '@posthog/http-request', // post incident.io update
        ])

        // Prove the bring-your-own-token wiring actually fired. The agent's
        // tool calls reference `${SLACK_BOT_TOKEN}`; we expect the runner to
        // have substituted the resolved value before each request went out.
        // Captured fetch headers should NEVER contain the literal placeholder.
        expect(slackCalls).toHaveLength(3)
        for (const call of slackCalls) {
            expect(call.method).toBe('POST')
            expect(call.auth).toBe('Bearer xoxb-test-token')
            expect(call.auth).not.toContain('${') // no unsubstituted placeholders
        }
        // Spot-check the three Slack endpoints we expected to hit.
        const endpoints = slackCalls.map((c) => c.url.replace('https://slack.com/api/', '')).sort()
        expect(endpoints).toEqual(['chat.postMessage', 'conversations.history', 'reactions.add'])

        // incident.io substitution mirrors the Slack flow: the two
        // recorded calls (list active incidents + post resolved update)
        // must carry the resolved INCIDENT_IO_TOKEN, never the placeholder.
        expect(incidentCalls).toHaveLength(2)
        for (const call of incidentCalls) {
            expect(call.auth).toBe('Bearer inc_test_token')
            expect(call.auth).not.toContain('${')
        }
        const incidentEndpoints = incidentCalls
            .map((c) => c.url.replace('https://api.incident.io/v2/', '').split('?')[0])
            .sort()
        expect(incidentEndpoints).toEqual(['incidents', 'incidents/01HXYZ/updates'])
        expect(incidentCalls[1].method).toBe('POST')
        expect(incidentCalls[1].body).toMatchObject({ incident_id: '01HXYZ' })

        // Confirm the row actually landed in the tabular store — proves the
        // tool wired through to a real S3 backend, not just executed in a vacuum.
        const rows = await c.tabularStore.query(
            { teamId: session!.team_id, applicationId: session!.application_id },
            'incidents',
            { where: { alert_signature: 'ingestion-500s' } }
        )
        expect(rows).toHaveLength(1)
        expect(rows[0]).toMatchObject({
            alert_signature: 'ingestion-500s',
            mitigation: 'scaled consumer group, lag drained in 4m',
        })
    })
})
