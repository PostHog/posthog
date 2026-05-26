import { postSlack, readPrincipal } from '../harness/clients'
/**
 * Slack identity e2e — every shape of Layer-2 identity resolution against
 * real Postgres + the Django-owned `agent_stack_*` tables. Each happy case
 * asserts both the stamped `user` principal AND that the AgentUser row was
 * actually persisted in the identity space.
 */
import { type AgentCluster, startCluster } from '../harness/cluster'
import { createApp, createIdentitySpace, setTeamSecret } from '../harness/fixtures'

const TEAM_SECRET = 'e2e-slack-team-secret'
const SLACK_SIGNING_SECRET = 'e2e-slack-signing'
const TRUSTED_WORKSPACE = 'T_E2E_TRUSTED'
const UNTRUSTED_WORKSPACE = 'T_E2E_UNTRUSTED'

describe('Slack identity e2e', () => {
    let cluster: AgentCluster
    let spaceId: string

    beforeAll(async () => {
        cluster = await startCluster({ secrets: { SLACK_SIGNING_SECRET } })
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
        const space = await createIdentitySpace(cluster.cleanup, 'e2e-slack')
        spaceId = space.spaceId
    }, 30_000)

    afterAll(async () => {
        if (!cluster) {
            return
        }
        await cluster.cleanup.runAll()
        await cluster.stop()
    }, 30_000)

    async function makeSlackAgent(suffix: string, trusted: '*' | string[]): Promise<{ slug: string }> {
        return createApp(cluster.cleanup, {
            slugSuffix: suffix,
            auth: { type: 'webhook_signature', provider: 'slack' },
            identity: { space: 'e2e-slack', source: { provider: 'slack', trusted_workspaces: trusted } },
            triggers: [
                {
                    id: 'slack',
                    type: 'slack_event',
                    events: ['app_mention'],
                    signing_secret_name: 'SLACK_SIGNING_SECRET',
                },
            ],
        })
    }

    it('trusted workspace → 202 + user principal + AgentUser row persisted', async () => {
        const app = await makeSlackAgent('slack-trusted', [TRUSTED_WORKSPACE])
        const res = await postSlack(cluster, app.slug, {
            teamId: TRUSTED_WORKSPACE,
            userId: 'U_TRUSTED',
            signingSecret: SLACK_SIGNING_SECRET,
        })
        expect(res.status).toBe(202)
        const principal = await readPrincipal(cluster, res.body.sessionId)
        expect(principal).toMatchObject({
            kind: 'user',
            spaceId,
            provider: 'slack',
            providerAccountId: TRUSTED_WORKSPACE,
            providerSubject: 'U_TRUSTED',
        })
        // Django persistence side-effect: the AgentUser + UserIdentity rows exist.
        const { rows } = await cluster.posthog.query<{ id: string }>(
            `SELECT au.id::text AS id
             FROM agent_stack_useridentity ui
             JOIN agent_stack_agentuser au ON au.id = ui.user_id
             WHERE ui.space_id = $1 AND ui.provider = 'slack'
               AND ui.provider_account_id = $2 AND ui.provider_subject = 'U_TRUSTED'`,
            [spaceId, TRUSTED_WORKSPACE]
        )
        expect(rows).toHaveLength(1)
        expect((principal as { userId: string }).userId).toBe(rows[0].id)
    })

    it('untrusted workspace on a trusted-list agent → 403', async () => {
        const app = await makeSlackAgent('slack-untrusted', [TRUSTED_WORKSPACE])
        const res = await postSlack(cluster, app.slug, {
            teamId: UNTRUSTED_WORKSPACE,
            userId: 'U_X',
            signingSecret: SLACK_SIGNING_SECRET,
        })
        expect(res.status).toBe(403)
    })

    it('"*" allowlist (B2C) accepts any workspace; distinct (workspace, user) → distinct AgentUsers', async () => {
        const app = await makeSlackAgent('slack-b2c', '*')
        const a = await postSlack(cluster, app.slug, {
            teamId: 'T_B2C_X',
            userId: 'U_X',
            signingSecret: SLACK_SIGNING_SECRET,
        })
        const b = await postSlack(cluster, app.slug, {
            teamId: 'T_B2C_Y',
            userId: 'U_Y',
            signingSecret: SLACK_SIGNING_SECRET,
        })
        expect(a.status).toBe(202)
        expect(b.status).toBe(202)
        const pa = (await readPrincipal(cluster, a.body.sessionId)) as { userId: string }
        const pb = (await readPrincipal(cluster, b.body.sessionId)) as { userId: string }
        expect(pa.userId).not.toBe(pb.userId)
    })

    it('same (workspace, user) tuple resolves to the same AgentUser across sessions (stable id)', async () => {
        const app = await makeSlackAgent('slack-stable', [TRUSTED_WORKSPACE])
        const first = await postSlack(cluster, app.slug, {
            teamId: TRUSTED_WORKSPACE,
            userId: 'U_STABLE',
            signingSecret: SLACK_SIGNING_SECRET,
        })
        const second = await postSlack(cluster, app.slug, {
            teamId: TRUSTED_WORKSPACE,
            userId: 'U_STABLE',
            signingSecret: SLACK_SIGNING_SECRET,
        })
        expect(first.status).toBe(202)
        expect(second.status).toBe(202)
        const p1 = (await readPrincipal(cluster, first.body.sessionId)) as { userId: string }
        const p2 = (await readPrincipal(cluster, second.body.sessionId)) as { userId: string }
        expect(p1.userId).toBe(p2.userId)
    })
})
