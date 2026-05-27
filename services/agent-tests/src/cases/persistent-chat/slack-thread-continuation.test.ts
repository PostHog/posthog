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
import { postSlack, readSessionRow, waitForAwaitingInput } from '../../harness/clients'
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, createIdentitySpace, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-chat-slack-team-secret'
const SLACK_SIGNING_SECRET = 'e2e-chat-slack-signing'
const TRUSTED_WORKSPACE = 'T_CHAT_TRUSTED'

describe('persistent-chat: Slack thread continuation', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
        await createIdentitySpace(cluster.cleanup, 'e2e-chat-slack')
    }, 30_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    async function makeSlackApp(slugSuffix: string): Promise<{ slug: string }> {
        return createApp(cluster.cleanup, {
            slugSuffix,
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
    }

    it('second app_mention in the same thread routes to the existing session as /send', async () => {
        const app = await makeSlackApp('chat-slack-thread')
        const threadTs = '1735000000.001234'

        const first = await postSlack(cluster, app.slug, {
            teamId: TRUSTED_WORKSPACE,
            userId: 'U_THREAD_OWNER',
            signingSecret: SLACK_SIGNING_SECRET,
            extraEvent: { ts: threadTs, channel: 'C_THREAD', text: 'hi bot' },
        })
        expect(first.status).toBe(202)
        const sessionId = first.body.sessionId as string

        // Park after turn 1 — chat-echo replies + awaiting_input.
        await waitForAwaitingInput(cluster, sessionId, { afterTurn: 1 })

        // Reply in the same thread: same workspace, channel, thread_ts,
        // user. The ingress reuses the session and the second event's
        // text becomes a /send into the existing one.
        const second = await postSlack(cluster, app.slug, {
            teamId: TRUSTED_WORKSPACE,
            userId: 'U_THREAD_OWNER',
            signingSecret: SLACK_SIGNING_SECRET,
            extraEvent: { ts: '1735000000.002000', thread_ts: threadTs, channel: 'C_THREAD', text: 'follow-up' },
        })
        expect(second.status).toBe(202)
        expect(second.body.sessionId).toBe(sessionId)
        expect(second.body.continued).toBe(true)

        // Turn 2 picks up the follow-up. state.messages has both user
        // events; the second one is the Slack reply text.
        const afterTurn2 = await waitForAwaitingInput(cluster, sessionId, { afterTurn: 2 })
        const userMsgs = afterTurn2.state?.messages.filter((m) => m.role === 'user').map((m) => m.content)
        expect(userMsgs).toContain('follow-up')
    })

    it('mentions in distinct threads create distinct sessions', async () => {
        const app = await makeSlackApp('chat-slack-distinct-threads')

        const a = await postSlack(cluster, app.slug, {
            teamId: TRUSTED_WORKSPACE,
            userId: 'U_DISTINCT',
            signingSecret: SLACK_SIGNING_SECRET,
            extraEvent: { ts: '1735000000.111111', channel: 'C_THREAD', text: 'first thread' },
        })
        const b = await postSlack(cluster, app.slug, {
            teamId: TRUSTED_WORKSPACE,
            userId: 'U_DISTINCT',
            signingSecret: SLACK_SIGNING_SECRET,
            extraEvent: { ts: '1735000000.222222', channel: 'C_THREAD', text: 'second thread' },
        })
        expect(a.status).toBe(202)
        expect(b.status).toBe(202)
        expect(a.body.sessionId).not.toBe(b.body.sessionId)
    })

    it('different Slack user replying in the same thread gets its own session', async () => {
        // The external_key is `slack:<workspace>:<channel>:<thread>:<user>` —
        // including the user. Two users in the same thread get
        // independent sessions; the strict-principal-match on /send
        // would have blocked routing them to the same session anyway.
        const app = await makeSlackApp('chat-slack-multi-user')
        const threadTs = '1735000000.333333'

        const owner = await postSlack(cluster, app.slug, {
            teamId: TRUSTED_WORKSPACE,
            userId: 'U_OWNER',
            signingSecret: SLACK_SIGNING_SECRET,
            extraEvent: { ts: threadTs, channel: 'C_THREAD', text: 'I started it' },
        })
        const other = await postSlack(cluster, app.slug, {
            teamId: TRUSTED_WORKSPACE,
            userId: 'U_OTHER',
            signingSecret: SLACK_SIGNING_SECRET,
            extraEvent: { ts: '1735000000.444444', thread_ts: threadTs, channel: 'C_THREAD', text: 'me too' },
        })
        expect(owner.status).toBe(202)
        expect(other.status).toBe(202)
        expect(owner.body.sessionId).not.toBe(other.body.sessionId)
    })

    it('a completed thread starts a fresh session on the next mention', async () => {
        // The partial unique index on external_key only enforces
        // uniqueness for non-terminal sessions. Closing a session and
        // mentioning again with the same thread_ts spawns a brand-new
        // session (and the new one claims the key).
        const app = await makeSlackApp('chat-slack-completed')
        const threadTs = '1735000000.555555'

        // Force-complete by using chat-once for this app — first
        // mention completes immediately. Cluster-level encryptedEnv
        // is per-app so we don't pollute the shared cluster.
        // Per-app override:
        const completedApp = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-slack-completed-once',
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
            encryptedEnv: { SLACK_SIGNING_SECRET, __TEST_EXECUTOR: 'chat-once' },
        })
        // Avoid the unused `app` lint warning. The completedApp drives the test.
        expect(app.slug).toBeTruthy()

        const first = await postSlack(cluster, completedApp.slug, {
            teamId: TRUSTED_WORKSPACE,
            userId: 'U_RESPAWN',
            signingSecret: SLACK_SIGNING_SECRET,
            extraEvent: { ts: threadTs, channel: 'C_THREAD', text: 'once' },
        })

        // Wait until the first session is terminal.
        const start = Date.now()
        while (Date.now() - start < 5_000) {
            const row = await readSessionRow(cluster, first.body.sessionId)
            if (row?.status === 'completed') {
                break
            }
            await new Promise((r) => setTimeout(r, 50))
        }

        const second = await postSlack(cluster, completedApp.slug, {
            teamId: TRUSTED_WORKSPACE,
            userId: 'U_RESPAWN',
            signingSecret: SLACK_SIGNING_SECRET,
            extraEvent: { ts: '1735000000.666666', thread_ts: threadTs, channel: 'C_THREAD', text: 'again' },
        })
        expect(second.status).toBe(202)
        expect(second.body.sessionId).not.toBe(first.body.sessionId)
        expect(second.body.continued).toBeUndefined()
    })
})
