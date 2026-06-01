/**
 * Cross-team isolation: a PAT scoped to team A cannot be used to access an
 * agent owned by team B. The auth provider verifies the PAT is scoped to the
 * agent's owning team.
 *
 * Old equivalent: isolated/cross-team.test.ts.
 */

import request from 'supertest'

import { AuthProvider, publicVerifier, readBearer } from '@posthog/agent-ingress'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

const TEAM_A_PAT = 'team-a-token'
const TEAM_B_PAT = 'team-b-token'

// PAT → team mapping; the verifier rejects the PAT if it's not scoped to the agent's team.
const provider: AuthProvider = {
    verifiers: [
        publicVerifier,
        {
            modeType: 'pat',
            async verify(req, _mode, application) {
                const bearer = readBearer(req)
                if (!bearer) {
                    return { ok: false, status: 0, reason: 'skip' }
                }
                const teamForToken = bearer === TEAM_A_PAT ? 100 : bearer === TEAM_B_PAT ? 200 : -1
                if (teamForToken !== application.team_id) {
                    return { ok: false, status: 401, reason: 'invalid_token' }
                }
                return {
                    ok: true,
                    principal: {
                        kind: 'posthog',
                        source: 'pat',
                        user_id: bearer,
                        team_id: teamForToken,
                    },
                    credentials: { posthog_api: { kind: 'pat_bearer', token: bearer } },
                }
            },
        },
    ],
}

describe('cross-team isolation: real e2e', () => {
    let cA: Cluster

    beforeEach(async () => {
        cA = await buildCluster({ authProvider: provider, teamId: 100 })
    })

    afterEach(async () => {
        await cA.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('team A PAT against a team A agent → 200', async () => {
        await cA.deployAgent({
            slug: 'team-a-bot',
            spec: { auth: { modes: [{ type: 'pat' }] } },
        })
        const res = await request(cA.ingress)
            .post('/agents/team-a-bot/run')
            .set('authorization', `Bearer ${TEAM_A_PAT}`)
            .send({ message: 'x' })
        expect(res.status).toBe(200)
        expect(res.body.principal.team_id).toBe(100)
    })

    it('team B PAT against a team A agent → 401 (team-scoping closes)', async () => {
        await cA.deployAgent({
            slug: 'team-a-secured',
            spec: { auth: { modes: [{ type: 'pat' }] } },
        })
        const res = await request(cA.ingress)
            .post('/agents/team-a-secured/run')
            .set('authorization', `Bearer ${TEAM_B_PAT}`)
            .send({ message: 'x' })
        expect(res.status).toBe(401)
    })

    it('totally unknown PAT → 401', async () => {
        await cA.deployAgent({
            slug: 'team-a-secured2',
            spec: { auth: { modes: [{ type: 'pat' }] } },
        })
        const res = await request(cA.ingress)
            .post('/agents/team-a-secured2/run')
            .set('authorization', 'Bearer rogue-token')
            .send({ message: 'x' })
        expect(res.status).toBe(401)
    })
})
