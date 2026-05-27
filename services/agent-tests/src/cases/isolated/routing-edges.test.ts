/**
 * Routing-edge e2e — failure modes around tenant resolution and trigger
 * dispatch that the happy-path tests don't reach.
 *
 *   - agent has a slack-only trigger; client posts /run → 404
 *     (route() reaches `no trigger registered for ...`)
 *   - revision is not in `ready` state → 409
 *     (server.ts gates dispatch on revisionState; the resolver still
 *     finds the row because it only filters by deployment_status)
 *   - unknown host → 404 (no revision for that host)
 *
 * Together these prove the 4xx envelope the gateway returns is stable
 * for ops to alert on.
 */
import supertest from 'supertest'

import { post } from '../../harness/clients'
import { hostFor } from '../../harness/clients'
import { type AgentCluster, startCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-routing-team-secret'
const SLACK_SIGNING_SECRET = 'e2e-routing-slack-signing'

describe('routing edges', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await startCluster({ secrets: { SLACK_SIGNING_SECRET } })
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
    }, 30_000)

    afterAll(async () => {
        if (!cluster) {
            return
        }
        await cluster.cleanup.runAll()
        await cluster.stop()
    }, 30_000)

    it('agent has only a slack trigger — POST /run → 404 (no trigger for the request)', async () => {
        // public auth keeps the test focused on routing, not auth.
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'routing-slack-only',
            auth: { type: 'webhook_signature', provider: 'slack' },
            triggers: [
                {
                    id: 'slack',
                    type: 'slack_event',
                    events: ['app_mention'],
                    signing_secret_name: 'SLACK_SIGNING_SECRET',
                },
            ],
        })
        const res = await post(cluster, app.slug, { pat: TEAM_SECRET })
        // route() rejects: `no trigger registered for POST /run`.
        expect(res.status).toBe(404)
    })

    it('revision in `building` state — POST /run → 409 (resolver returns it; server gates dispatch)', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'routing-not-ready',
            auth: { type: 'pat' },
            revisionState: 'building',
        })
        const res = await post(cluster, app.slug, { pat: TEAM_SECRET })
        expect(res.status).toBe(409)
        expect(res.body.error).toMatch(/revision not ready/)
    })

    it('unknown host (no agent for slug) → 404', async () => {
        const res = await supertest(cluster.ingressUrl)
            .post('/run')
            .set('x-original-host', hostFor('e2e-routing-does-not-exist'))
            .set('authorization', `Bearer ${TEAM_SECRET}`)
            .set('content-type', 'application/json')
            .send('{}')
        expect(res.status).toBe(404)
        expect(res.body.error).toMatch(/application not found/)
    })

    it('host outside the configured domain suffix → 400', async () => {
        const res = await supertest(cluster.ingressUrl)
            .post('/run')
            .set('x-original-host', 'evil.example.com')
            .set('content-type', 'application/json')
            .send('{}')
        expect(res.status).toBe(400)
        expect(res.body.error).toMatch(/host does not match/)
    })
})
