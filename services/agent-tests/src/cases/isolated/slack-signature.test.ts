/**
 * Slack signature failure-path e2e.
 *
 * `slack-identity.test.ts` covers the happy paths and the workspace-trust
 * checks. This file covers what the route does when the request can't be
 * authenticated as Slack at all — the four reasons `verifySlackSignature`
 * can reject:
 *
 *   - missing `x-slack-signature`
 *   - missing `x-slack-request-timestamp`
 *   - stale timestamp (older than the 5-minute window)
 *   - signature mismatch (wrong signing secret)
 *
 * All four map to 401 in `route()`; the body's `error` field distinguishes
 * them. The point of testing each individually is to catch silent
 * defaults — e.g. an off-by-one in the staleness window, or a regression
 * that treats a missing timestamp the same as a stale one.
 */
import { createHmac } from 'node:crypto'
import supertest from 'supertest'

import { hostFor } from '../../harness/clients'
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, createIdentitySpace, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-slack-sig-team-secret'
const SLACK_SIGNING_SECRET = 'e2e-slack-sig-signing'
const TRUSTED_WORKSPACE = 'T_SIGTEST'

const PAYLOAD = JSON.stringify({
    type: 'event_callback',
    team_id: TRUSTED_WORKSPACE,
    event: { type: 'app_mention', channel: 'C', user: 'U', text: 'e2e' },
})

function freshTimestamp(): string {
    return String(Math.floor(Date.now() / 1000))
}

function sign(secret: string, timestamp: string, body: string): string {
    return 'v0=' + createHmac('sha256', secret).update(`v0:${timestamp}:${body}`).digest('hex')
}

describe('slack signature failure paths', () => {
    let cluster: AgentCluster
    let slug: string

    beforeAll(async () => {
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
        await createIdentitySpace(cluster.cleanup, 'e2e-slack-sig')
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'slack-sig',
            auth: { type: 'webhook_signature', provider: 'slack' },
            identity: {
                space: 'e2e-slack-sig',
                source: { provider: 'slack', trusted_workspaces: [TRUSTED_WORKSPACE] },
            },
            triggers: [
                {
                    id: 'slack',
                    type: 'slack_event',
                    events: ['app_mention'],
                    signing_secret_name: 'SLACK_SIGNING_SECRET',
                },
            ],
            encryptedEnv: { SLACK_SIGNING_SECRET },
        })
        slug = app.slug
    }, 30_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    it('missing x-slack-signature → 401', async () => {
        const ts = freshTimestamp()
        const res = await supertest(cluster.ingressUrl)
            .post('/webhooks/slack')
            .set('x-original-host', hostFor(slug))
            .set('content-type', 'application/json')
            .set('x-slack-request-timestamp', ts)
            .send(PAYLOAD)
        expect(res.status).toBe(401)
        expect(res.body.error).toMatch(/missing_signature/)
    })

    it('missing x-slack-request-timestamp → 401', async () => {
        const ts = freshTimestamp()
        const res = await supertest(cluster.ingressUrl)
            .post('/webhooks/slack')
            .set('x-original-host', hostFor(slug))
            .set('content-type', 'application/json')
            .set('x-slack-signature', sign(SLACK_SIGNING_SECRET, ts, PAYLOAD))
            .send(PAYLOAD)
        expect(res.status).toBe(401)
        expect(res.body.error).toMatch(/missing_timestamp/)
    })

    it('stale timestamp (>5 minutes) → 401 (replay protection)', async () => {
        // 10 minutes in the past. Slack's window is ±5min so this is well outside.
        const staleTs = String(Math.floor(Date.now() / 1000) - 600)
        const res = await supertest(cluster.ingressUrl)
            .post('/webhooks/slack')
            .set('x-original-host', hostFor(slug))
            .set('content-type', 'application/json')
            .set('x-slack-signature', sign(SLACK_SIGNING_SECRET, staleTs, PAYLOAD))
            .set('x-slack-request-timestamp', staleTs)
            .send(PAYLOAD)
        expect(res.status).toBe(401)
        expect(res.body.error).toMatch(/timestamp_out_of_range/)
    })

    it('signature signed with wrong secret → 401', async () => {
        const ts = freshTimestamp()
        const res = await supertest(cluster.ingressUrl)
            .post('/webhooks/slack')
            .set('x-original-host', hostFor(slug))
            .set('content-type', 'application/json')
            .set('x-slack-signature', sign('wrong-secret', ts, PAYLOAD))
            .set('x-slack-request-timestamp', ts)
            .send(PAYLOAD)
        expect(res.status).toBe(401)
        expect(res.body.error).toMatch(/signature_mismatch/)
    })
})
