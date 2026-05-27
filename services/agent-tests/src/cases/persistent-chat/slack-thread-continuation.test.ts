/**
 * Case 5: Slack thread → same session, multi-turn.
 *
 * Today: every `app_mention` enqueues a fresh `agent_sessions` row,
 * even when the user is replying in the same thread. The Slack
 * trigger captures `thread_ts` in the trigger input but nothing
 * looks it up.
 *
 * Spec contracts:
 *   - Posthog owns the mapping `(team_id, channel, thread_ts) ->
 *     session_id`. New table or new column on the existing schema —
 *     name it `agent_stack_slackthreadbinding` for now.
 *   - The Slack trigger's posthog-side resolver:
 *       - first lookup `(team_id, channel, thread_ts)`
 *       - if found AND the session is non-terminal → route as `/send`
 *         to that session (queues into `pendingInputs`)
 *       - else → enqueue a new session AND insert the binding
 *   - Identity resolution still runs per event; the principal stays
 *     the user who actually posted in Slack. Strict-match remains: a
 *     different Slack user posting in the same thread is its own
 *     question (do we route to the same session under a different
 *     principal? doc says no — distinct sessions per `(thread, user)`
 *     tuple). Pin the chosen rule.
 *   - The first message of a NEW thread session goes through the
 *     normal `/run` path (initialInput); follow-ups go through the
 *     `/send` path (pendingInputs).
 */
import { postSlack } from '../../harness/clients'
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, createIdentitySpace, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-chat-slack-team-secret'
const SLACK_SIGNING_SECRET = 'e2e-chat-slack-signing'
const TRUSTED_WORKSPACE = 'T_CHAT_TRUSTED'

describe.skip('persistent-chat: Slack thread continuation', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
        await createIdentitySpace(cluster.cleanup, 'e2e-chat-slack')
    }, 30_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    it('second app_mention in the same thread routes to the existing session as /send', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-slack-thread',
            auth: { type: 'webhook_signature', provider: 'slack' },
            identity: {
                space: 'e2e-chat-slack',
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
            encryptedEnv: { SLACK_SIGNING_SECRET, __TEST_EXECUTOR: 'chat-echo' },
        })

        const threadTs = '1735000000.001234'

        const first = await postSlack(cluster, app.slug, {
            teamId: TRUSTED_WORKSPACE,
            userId: 'U_THREAD_OWNER',
            signingSecret: SLACK_SIGNING_SECRET,
            extraEvent: { ts: threadTs, channel: 'C_THREAD' },
        })
        expect(first.status).toBe(202)
        const sessionId = first.body.sessionId as string

        const second = await postSlack(cluster, app.slug, {
            teamId: TRUSTED_WORKSPACE,
            userId: 'U_THREAD_OWNER',
            signingSecret: SLACK_SIGNING_SECRET,
            extraEvent: { ts: '1735000000.002000', thread_ts: threadTs, channel: 'C_THREAD' },
        })
        expect(second.status).toBe(202)
        // The SECOND mention does NOT create a new session.
        expect(second.body.sessionId).toBe(sessionId)

        // The binding row exists.
        // const bindings = await cluster.posthog.query(
        //   `SELECT session_id::text FROM agent_stack_slackthreadbinding
        //    WHERE team_id = $1 AND channel = $2 AND thread_ts = $3`,
        //   [1, 'C_THREAD', threadTs]
        // )
        // expect(bindings.rows).toHaveLength(1)
        // expect(bindings.rows[0].session_id).toBe(sessionId)

        // The conversation has both messages.
        // const state = await readSessionState(cluster, sessionId)
        // expect(state.messages.filter(m => m.role === 'user').length).toBe(2)
    })

    it('mentions in distinct threads create distinct sessions', async () => {
        // Two app_mention events with different thread_ts → two
        // sessions. The binding table has both. Each session evolves
        // independently.
    })

    it('a different Slack user replying in the same thread → distinct session (principal scope)', async () => {
        // U_OWNER opens a thread; U_OTHER replies. We do NOT route to
        // U_OWNER's session — that would let users hijack each other's
        // agent context. New session, new binding keyed by
        // (channel, thread_ts, user) if the agent has an identity:
        // block, OR a 403 if the agent doesn't allow this. Pin the
        // chosen behaviour.
    })

    it('the binding only matches non-terminal sessions; a completed thread starts a fresh session', async () => {
        // Bound session is `completed` or `failed` → the binding is
        // either deleted on terminal-state transitions OR is skipped
        // by the resolver. New mention spawns a new session and a
        // fresh binding. Pin which strategy we pick.
    })
})
