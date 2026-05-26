import { post, postSlack, send } from '../harness/clients'
/**
 * Session-control strict-match e2e. The control endpoints (`/listen`,
 * `/send`, `/cancel`) gate the caller's re-resolved principal against the
 * one stamped at session creation. This file proves both halves:
 *
 *   - same principal as creator → 202 (control op passes through)
 *   - different principal → 403 (mismatch surfaced from ingress)
 *
 * Slack-started sessions can't be `/send`-ed by the same Slack user via
 * HTTP (you can't sign a /send request); control falls back to `pat`, so
 * a PAT caller authenticates but the service principal it produces
 * doesn't match the session's user principal — 403.
 */
import { type AgentCluster, startCluster } from '../harness/cluster'
import { PrincipalEchoExecutor } from '../harness/executors'
import { createApp, createIdentitySpace, setTeamSecret } from '../harness/fixtures'

const TEAM_SECRET = 'e2e-strict-team-secret'
const SLACK_SIGNING_SECRET = 'e2e-strict-slack-signing'

describe('strict principal-match on /send', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await startCluster({
            executor: new PrincipalEchoExecutor(),
            secrets: { SLACK_SIGNING_SECRET },
        })
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
        await createIdentitySpace(cluster.cleanup, 'e2e-slack')
    }, 30_000)

    afterAll(async () => {
        if (!cluster) {
            return
        }
        await cluster.cleanup.runAll()
        await cluster.stop()
    }, 30_000)

    it('pat agent: /send with the same PAT as the creator → 202', async () => {
        const app = await createApp(cluster.cleanup, { slugSuffix: 'strict-pat-ok', auth: { type: 'pat' } })
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET })
        expect(run.status).toBe(202)
        const followup = await send(cluster, app.slug, run.body.sessionId, 'hi there', { pat: TEAM_SECRET })
        expect(followup.status).toBe(202)
    })

    it('pat agent: /send with wrong PAT → 401 (auth fails before strict-match)', async () => {
        const app = await createApp(cluster.cleanup, { slugSuffix: 'strict-pat-wrong', auth: { type: 'pat' } })
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET })
        expect(run.status).toBe(202)
        const followup = await send(cluster, app.slug, run.body.sessionId, 'hi there', { pat: 'wrong-pat' })
        expect(followup.status).toBe(401)
    })

    it('slack-started session: /send with valid PAT → 403 (service principal does not match user principal)', async () => {
        // Build a Slack agent. The session is started by an inbound webhook
        // (yields a `user` principal). Control endpoints for a
        // `webhook_signature` agent fall back to `pat`, so presenting the
        // team PAT authenticates — but the resulting `service` principal
        // does not equal the `user` principal stamped on the session.
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'strict-slack-mismatch',
            auth: { type: 'webhook_signature', provider: 'slack' },
            identity: { space: 'e2e-slack', source: { provider: 'slack', trusted_workspaces: ['T_OWNER'] } },
            triggers: [
                {
                    id: 'slack',
                    type: 'slack_event',
                    events: ['app_mention'],
                    signing_secret_name: 'SLACK_SIGNING_SECRET',
                },
            ],
        })
        const run = await postSlack(cluster, app.slug, {
            teamId: 'T_OWNER',
            userId: 'U_OWNER',
            signingSecret: SLACK_SIGNING_SECRET,
        })
        expect(run.status).toBe(202)
        const followup = await send(cluster, app.slug, run.body.sessionId, 'hi there', { pat: TEAM_SECRET })
        expect(followup.status).toBe(403)
    })

    it('public agent: /send without auth → 202 (both principals are null, no strict-match conflict)', async () => {
        const app = await createApp(cluster.cleanup, { slugSuffix: 'strict-public', auth: { type: 'public' } })
        const run = await post(cluster, app.slug)
        expect(run.status).toBe(202)
        const followup = await send(cluster, app.slug, run.body.sessionId, 'hi there')
        expect(followup.status).toBe(202)
    })
})
