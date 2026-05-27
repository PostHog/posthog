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
import { post, send } from '../../harness/clients'
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-chat-basic-team-secret'

describe.skip('persistent-chat: basic multi-turn over /send', () => {
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
            slugSuffix: 'chat-basic',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'chat-echo' },
        })

        // Turn 1: kick off the session with an initial body.
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'hello' } })
        expect(run.status).toBe(202)
        const sessionId = run.body.sessionId as string

        // The chat-echo stub should reply, park the job, and emit
        // `awaiting_input` rather than completing.
        // TODO: helper `waitForAwaitingInput(cluster, sessionId)` reading
        // log_entries for `[meta] awaiting_input`.
        // expect(await waitForAwaitingInput(cluster, sessionId)).toMatchObject({ turn: 1 })

        // Turn 2: follow-up. `/send` MUST hit the DB before returning.
        const followup = await send(cluster, app.slug, sessionId, 'and another thing', { pat: TEAM_SECRET })
        expect(followup.status).toBe(202)

        // TODO: helper `readSessionState(cluster, sessionId)` deserializing
        // the queue's BYTEA `state` column.
        // const state = await readSessionState(cluster, sessionId)
        // expect(state.messages.map((m) => m.role)).toEqual([
        //   'user', 'assistant',   // turn 1
        //   'user', 'assistant',   // turn 2
        // ])
        // expect(state.messages[0].content).toBe('hello')
        // expect(state.messages[2].content).toBe('and another thing')
        // expect(state.pendingInputs).toHaveLength(0)  // drained
        // expect(state.turnCount).toBe(2)

        // log_entries carries both user→assistant pairs.
        // const rows = await cluster.clickhouse.logsForSession(sessionId)
        // expect(rows.filter(r => r.message.startsWith('[chat] user:')).length).toBe(2)
        // expect(rows.filter(r => r.message.startsWith('[chat] assistant:')).length).toBe(2)
    })

    it('initial `/run` body lands as state.messages[0] with role=user', async () => {
        // The first message of every session is whatever the trigger
        // produced (POST /run body for http_invoke, Slack event text for
        // slack_event). Today this is buried in state.initialInput as an
        // opaque dict; the chat model needs it normalized into messages[0].
        // TODO: pin the normalisation contract here.
    })

    it('the conversation history is fed back to the SDK on subsequent turns', async () => {
        // The whole point of persisting messages — the SDK has to see the
        // prior context. Stub executor reflects this back so we can
        // observe: turn 2's assistant message includes a marker that
        // shows the agent saw turn 1.
        // TODO: chat-echo stub emits e.g. `seen_turns=N` in the assistant
        // message; assert that turn 2's reply has seen_turns=2.
    })
})
