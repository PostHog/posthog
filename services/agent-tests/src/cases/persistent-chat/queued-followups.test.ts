/**
 * Cases 2 & 3: `/send` while the agent is mid-turn — queue, not drop.
 *
 * Today: any `/send` that arrives while the agent is doing work (LLM
 * generating, tool dispatching, anything other than suspended in
 * `ask_for_input`) is silently dropped. The client gets 202, the
 * runner logs `user_message dropped`, the message is gone.
 *
 * Spec contracts:
 *   - `/send` is durable: ingress writes to `state.pendingInputs` in
 *     Postgres BEFORE returning 202.
 *   - The bus is used only as a wake-up signal — a pubsub notification
 *     that the parked job has new input, so the worker holding the
 *     job can advance its `scheduled_at` to NOW.
 *   - Multiple `/send` during one turn → multiple `pendingInputs[]`
 *     entries. Order preserved.
 *   - When the turn ends, the executor takes ALL pendingInputs as the
 *     next turn's user message(s) — either concatenated or as a series
 *     of turns (decision to make; this suite pins ordering either way).
 *   - If the runner is alive but the turn is mid-LLM-call, the
 *     additional `/send` does NOT interrupt — it queues.
 */
import { post, readSessionRow, send, waitForAwaitingInput, waitForStatus } from '../../harness/clients'
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-chat-queue-team-secret'

describe('persistent-chat: queued follow-ups during an in-flight turn', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
    }, 30_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    it('a /send during a slow turn appends to pendingInputs in DB and is NOT dropped', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-queue-one',
            // chat-slow: holds the turn for ~3s, then echoes + awaiting_input.
            // Override to a shorter 800ms so the test runs fast — long
            // enough to land a /send during the turn but short enough
            // not to dominate the suite's wall time.
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'chat-slow', __TEST_CHAT_SLEEP_MS: '800' },
        })

        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'first' } })
        const sessionId = run.body.sessionId as string

        // Wait until the worker has dequeued the job and is inside the
        // executor's sleep — that's when /send mid-turn is meaningful.
        await waitForStatus(cluster, sessionId, ['running'], { timeoutMs: 5_000 })

        const followup = await send(cluster, app.slug, sessionId, 'queue me', { pat: TEAM_SECRET })
        expect(followup.status).toBe(202)

        // The /send wrote to the pending_inputs column BEFORE returning
        // 202. The turn is still running; column visibility proves
        // durability didn't ride on the bus.
        const mid = await readSessionRow(cluster, sessionId)
        expect(mid?.pendingInputsColumn.map((p) => p.content)).toEqual(['queue me'])

        // Turn 2 picks up the queued input and produces another
        // user→assistant pair; pending_inputs drains to [].
        const afterTurn2 = await waitForAwaitingInput(cluster, sessionId, { afterTurn: 2 })
        expect(afterTurn2.pendingInputsColumn).toHaveLength(0)
        const userMsgs = afterTurn2.state?.messages.filter((m) => m.role === 'user').map((m) => m.content)
        expect(userMsgs).toEqual(['first', 'queue me'])
    })

    it('three /sends mid-turn → pendingInputs[] has all three in arrival order; next turn drains them all', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-queue-three',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'chat-slow', __TEST_CHAT_SLEEP_MS: '800' },
        })

        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'go' } })
        const sessionId = run.body.sessionId as string

        await waitForStatus(cluster, sessionId, ['running'], { timeoutMs: 5_000 })

        await send(cluster, app.slug, sessionId, 'one', { pat: TEAM_SECRET })
        await send(cluster, app.slug, sessionId, 'two', { pat: TEAM_SECRET })
        await send(cluster, app.slug, sessionId, 'three', { pat: TEAM_SECRET })

        // All three durably queued during the in-flight turn.
        const mid = await readSessionRow(cluster, sessionId)
        expect(mid?.pendingInputsColumn.map((p) => p.content)).toEqual(['one', 'two', 'three'])

        // After turn 2 the queue is drained AND all three user messages
        // are in state.messages, in order, alongside the initial 'go'.
        const afterTurn2 = await waitForAwaitingInput(cluster, sessionId, { afterTurn: 2 })
        expect(afterTurn2.pendingInputsColumn).toHaveLength(0)
        const userMsgs = afterTurn2.state?.messages.filter((m) => m.role === 'user').map((m) => m.content)
        expect(userMsgs).toEqual(['go', 'one', 'two', 'three'])
    })

    it('a /send that arrives BEFORE the worker has dequeued the job is still durable', async () => {
        // The load-bearing claim: regardless of who wins the race
        // (worker dequeues first vs /send writes first), 'race me'
        // ends up in state.messages — never dropped. Two valid
        // outcomes:
        //   (a) /send wins → 'race me' drains into turn 1; turnCount=1
        //   (b) worker wins → 'race me' parked, drained into turn 2;
        //       turnCount=2
        // Both must contain ['kick', 'race me'] in user messages.
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-queue-early',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'chat-slow', __TEST_CHAT_SLEEP_MS: '300' },
        })
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'kick' } })
        const sessionId = run.body.sessionId as string

        // No `waitForStatus(running)` — let the race happen.
        const followup = await send(cluster, app.slug, sessionId, 'race me', { pat: TEAM_SECRET })
        expect(followup.status).toBe(202)

        // Wait for either turn 1 (race (a)) or turn 2 (race (b)) to
        // settle — whichever side wins, the row should reach a state
        // where pending_inputs is drained AND both user messages are
        // present in state.messages.
        const start = Date.now()
        while (Date.now() - start < 10_000) {
            const row = await readSessionRow(cluster, sessionId)
            if (row && row.status === 'available' && row.pendingInputsColumn.length === 0) {
                const userMsgs = row.state?.messages.filter((m) => m.role === 'user').map((m) => m.content) ?? []
                if (userMsgs.includes('kick') && userMsgs.includes('race me')) {
                    expect(userMsgs).toEqual(['kick', 'race me'])
                    return
                }
            }
            await new Promise((r) => setTimeout(r, 50))
        }
        throw new Error('race-durability: never saw both messages in state.messages')
    })
})
