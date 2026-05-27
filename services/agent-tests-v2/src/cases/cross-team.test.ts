/**
 * Cross-team isolation: a PAT scoped to team A cannot be used to access an
 * agent owned by team B. The auth provider verifies the PAT is scoped to the
 * agent's owning team.
 *
 * Old equivalent: isolated/cross-team.test.ts.
 */

import request from 'supertest'

import { AuthProvider } from '@posthog/agent-ingress-v2'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

const TEAM_A_PAT = 'team-a-token'
const TEAM_B_PAT = 'team-b-token'

// PAT → team mapping; the provider rejects the PAT if it's not scoped to the agent's team.
const provider: AuthProvider = {
    async verifyPat(token, application) {
        const teamForToken = token === TEAM_A_PAT ? 100 : token === TEAM_B_PAT ? 200 : -1
        if (teamForToken !== application.team_id) {
            return null
        }
        return { kind: 'service', team_id: teamForToken, pat_id: token }
    },
    async verifyInternal() {
        return null
    },
    async verifySharedSecret() {
        return null
    },
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
            spec: { auth: { mode: 'pat' } },
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
            spec: { auth: { mode: 'pat' } },
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
            spec: { auth: { mode: 'pat' } },
        })
        const res = await request(cA.ingress)
            .post('/agents/team-a-secured2/run')
            .set('authorization', 'Bearer rogue-token')
            .send({ message: 'x' })
        expect(res.status).toBe(401)
    })
})
