/**
 * Case 1: basic multi-turn over `/send`.
 *
 * Pins the simplest version of "chat works": start a session, observe
 * the first assistant turn, send a follow-up, observe a second turn
 * that incorporates the follow-up. The whole conversation history must
 * live in the queue row's persisted `state.messages`, NOT in the
 * runner's in-process Promise.
 *
 * Spec contracts under test:
 *   - The executor reads `state.pendingInputs[0]` as the user message
 *     for each turn (not via a Redis pubsub waiter).
 *   - Each turn appends both the user input and the assistant reply
 *     to `state.messages`.
 *   - Between turns the queue row's status is `available` or a parked
 *     `awaiting_input` variant; the session is NOT pinned to one
 *     worker.
 *   - `/send` to a session in any non-terminal state succeeds and
 *     appends to `pendingInputs` synchronously — never silently dropped.
 *
 * This test uses the stub `chat-echo` executor (TBD) that echoes the
 * latest user input into the assistant reply and returns
 * `awaiting_input` after each turn. That's enough to verify turn
 * boundaries + state without paying Anthropic.
 */
import { post, readSessionRow, send, waitForAwaitingInput, waitForStatus } from '../../harness/clients'
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-chat-basic-team-secret'

describe('persistent-chat: basic multi-turn over /send', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
    }, 30_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    it('two-turn conversation: state.messages grows by turn; both user inputs visible in DB', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-basic-two-turn',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'chat-echo' },
        })

        // Turn 1: kick off the session with an initial body.
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'hello' } })
        expect(run.status).toBe(202)
        const sessionId = run.body.sessionId as string

        // chat-echo replies, returns awaiting_input — worker parks the
        // job at status=available with scheduled in the future.
        const afterTurn1 = await waitForAwaitingInput(cluster, sessionId, { afterTurn: 1 })
        expect(afterTurn1.state?.messages.map((m) => m.role)).toEqual(['user', 'assistant'])
        expect(afterTurn1.state?.messages[0].content).toBe('hello')
        expect(afterTurn1.state?.messages[1].content).toMatch(/^echo: hello/)
        expect(afterTurn1.state?.turnCount).toBe(1)

        // Turn 2: follow-up. `/send` writes to pending_inputs durably
        // AND advances `scheduled` to NOW so the worker picks the job
        // up immediately (no waiting for the 60s park to expire).
        const followup = await send(cluster, app.slug, sessionId, 'and another thing', { pat: TEAM_SECRET })
        expect(followup.status).toBe(202)

        const afterTurn2 = await waitForAwaitingInput(cluster, sessionId, { afterTurn: 2 })
        expect(afterTurn2.state?.messages.map((m) => m.role)).toEqual([
            'user',
            'assistant', // turn 1
            'user',
            'assistant', // turn 2
        ])
        expect(afterTurn2.state?.messages[2].content).toBe('and another thing')
        expect(afterTurn2.state?.messages[3].content).toMatch(/^echo: and another thing/)
        expect(afterTurn2.pendingInputsColumn).toHaveLength(0)
        expect(afterTurn2.state?.turnCount).toBe(2)
    })

    it('chat-once executor: completes after a single turn', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-basic-once',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'chat-once' },
        })
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'hi' } })
        const sessionId = run.body.sessionId as string

        await waitForStatus(cluster, sessionId, ['completed'])

        const row = await readSessionRow(cluster, sessionId)
        expect(row?.status).toBe('completed')
        expect(row?.state?.messages.map((m) => m.role)).toEqual(['user', 'assistant'])
        expect(row?.state?.messages[1].content).toMatch(/^once: hi/)
    })
})
