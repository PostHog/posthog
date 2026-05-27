import { post, readPrincipal } from '../../harness/clients'
/**
 * Cross-team PAT isolation e2e.
 *
 * The security boundary: ingress resolves the agent → revision → owning
 * team, and verifies the bearer token against THAT team's
 * `secret_api_token`. A PAT valid for team A must not authenticate
 * against an agent owned by team B, even if both teams live in the same
 * org and the request hits the same ingress process.
 *
 * The team-scoping closure lives at [services/agent-ingress/src/server.ts:182](
 * services/agent-ingress/src/server.ts). Without a real second team in
 * the DB this guarantee is untestable — we clone team 1 via
 * `createSecondaryTeam` to materialise the cross-team case.
 *
 * Coverage matrix:
 *   - team A PAT against team B agent → 401
 *   - team B PAT against team B agent → 202 (correct PAT works)
 *   - team A PAT against team A agent → 202 (sanity / control)
 *
 * Also verifies that when team B's PAT does authenticate the stamped
 * principal correctly reflects team B's orgId — not a hardcoded 1.
 */
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, createSecondaryTeam, setTeamSecret } from '../../harness/fixtures'

const TEAM_A_SECRET = 'e2e-team-a-secret'
const TEAM_B_SECRET = 'e2e-team-b-secret'

describe('cross-team PAT isolation', () => {
    let cluster: AgentCluster
    let teamBId: number

    beforeAll(async () => {
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_A_SECRET)
        const teamB = await createSecondaryTeam(cluster.cleanup, 'e2e-team-b', TEAM_B_SECRET)
        teamBId = teamB.teamId
    }, 30_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    it('team A PAT against a team B agent → 401 (team-scoping closure rejects)', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'cross-team-b',
            auth: { type: 'pat' },
            teamId: teamBId,
        })
        const res = await post(cluster, app.slug, { pat: TEAM_A_SECRET })
        expect(res.status).toBe(401)
    })

    it("team B's own PAT against the team B agent → 202 + service principal carries team B's orgId", async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'cross-team-b-own',
            auth: { type: 'pat' },
            teamId: teamBId,
        })
        const res = await post(cluster, app.slug, { pat: TEAM_B_SECRET })
        expect(res.status).toBe(202)
        expect(await readPrincipal(cluster, res.body.sessionId)).toEqual({
            kind: 'service',
            orgId: String(teamBId),
            caller: 'team-secret',
        })
    })

    it('team A PAT against a team A agent → 202 (control — proves the rejection above was team-scoped, not blanket)', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'cross-team-a-own',
            auth: { type: 'pat' },
        })
        const res = await post(cluster, app.slug, { pat: TEAM_A_SECRET })
        expect(res.status).toBe(202)
    })
})
