/**
 * Case 4: worker crash mid-session → resume from persisted state.
 *
 * The load-bearing test for the entire persistence story. If this
 * passes, all the others follow; if this fails, none of the rest is
 * meaningful (we're just paving an in-memory cowpath that breaks the
 * moment a runner dies).
 *
 * Today's failure mode: the SDK holds the conversation history inside
 * its iterator, and `ask_for_input` suspends on an in-process Promise.
 * Kill the runner subprocess and everything is gone — even though
 * `agent_sessions.state` exists, nothing has been written to it.
 *
 * Spec contracts:
 *   - `state.messages` is persisted by the executor after EVERY turn,
 *     before returning the outcome. Worker death after a successful
 *     turn loses at most the in-flight LLM call.
 *   - A killed-mid-turn job is reclaimed by the queue's janitor (heartbeat
 *     expiry) and rescheduled. New worker dequeues, deserializes state,
 *     resumes the conversation by passing `messages` to the SDK as
 *     prior context (via `resume: sessionId` or equivalent).
 *   - The SDK's own session is keyed off our `agent_sessions.id` (one
 *     UUID per session, used consistently across crashes) — so the SDK
 *     also rehydrates whatever it cares about.
 *   - User-facing: a `/send` after the crash succeeds normally; the
 *     resumed worker observes pendingInputs and treats them as the
 *     next turn.
 */
import { post, readSessionRow, send, waitForAwaitingInput, waitForStatus } from '../../harness/clients'
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-chat-resume-team-secret'

describe('persistent-chat: worker crash mid-session resumes cleanly', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
    }, 30_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    /**
     * Simulate a worker crash by directly resetting the queue row in
     * Postgres. The janitor does the same thing via heartbeat-expiry,
     * but its timeout is too long for a unit test. The effect is
     * identical: the orphaned worker's eventual ack/fail/cancel
     * UPDATEs match `WHERE lock_id = <old>` and affect zero rows; the
     * row sits at `available` with the new lock_id cleared, and any
     * runner dequeues it on the next poll.
     */
    async function simulateWorkerCrash(sessionId: string): Promise<void> {
        await cluster.queue.query(
            `UPDATE agent_sessions
             SET status = 'available',
                 lock_id = NULL,
                 last_heartbeat = NULL,
                 scheduled = NOW()
             WHERE id = $1 AND status = 'running'`,
            [sessionId]
        )
    }

    it('between turns: state persists; any runner can pick up and continue', async () => {
        // Turn 1 parks → state in DB → forcibly re-dequeue. The same
        // shared runner will pick the job up, but the point is that
        // ANY worker can — the lifecycle is decoupled from process
        // identity.
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-resume-between-turns',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'chat-echo' },
        })
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'before' } })
        const sessionId = run.body.sessionId as string

        const turn1 = await waitForAwaitingInput(cluster, sessionId, { afterTurn: 1 })
        expect(turn1.state?.messages.filter((m) => m.role === 'user').map((m) => m.content)).toEqual(['before'])

        // Different worker takes the job (via /send waking it up).
        await send(cluster, app.slug, sessionId, 'after', { pat: TEAM_SECRET })

        const turn2 = await waitForAwaitingInput(cluster, sessionId, { afterTurn: 2 })
        expect(turn2.state?.messages.filter((m) => m.role === 'user').map((m) => m.content)).toEqual([
            'before',
            'after',
        ])
    })

    it('mid-turn crash: state from prior turns survives; the in-flight turn replays cleanly', async () => {
        // chat-slow sleeps ~1.5s — enough time to inject a simulated
        // crash mid-turn. After turn 1 parks normally, /send wakes
        // turn 2. We yank the row to available WHILE turn 2 is
        // running. The orphaned worker's ack hits a zero-row UPDATE;
        // the new dequeue rebuilds from persisted state and completes
        // the turn for real.
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-resume-mid-turn',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'chat-slow', __TEST_CHAT_SLEEP_MS: '1500' },
        })
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'opener' } })
        const sessionId = run.body.sessionId as string
        await waitForAwaitingInput(cluster, sessionId, { afterTurn: 1, timeoutMs: 15_000 })

        await send(cluster, app.slug, sessionId, 'follow-up', { pat: TEAM_SECRET })
        // Wait until the worker has locked the row and started turn 2.
        await waitForStatus(cluster, sessionId, ['running'], { timeoutMs: 5_000 })

        // Simulate the running worker dying. The chat-slow sleep is
        // still in flight; this UPDATE doesn't kill it but it does
        // remove the lock, so the original worker's writeback won't
        // commit. Another dequeue picks the job up; if state was
        // properly persisted between turns it has 'opener' visible.
        await simulateWorkerCrash(sessionId)

        // The dequeue should happen within milliseconds. The new
        // worker takes the row, sees the persisted turn-1 messages
        // in state, processes turn 2 ('follow-up' is in state.messages
        // because the original worker pushed it before the executor
        // returned), and parks at awaiting_input again.
        const resumed = await waitForAwaitingInput(cluster, sessionId, { afterTurn: 2, timeoutMs: 15_000 })
        const userMsgs = resumed.state?.messages.filter((m) => m.role === 'user').map((m) => m.content)
        expect(userMsgs).toEqual(['opener', 'follow-up'])
    })

    it('mid-turn crash: pending_inputs queued during the dead turn are preserved', async () => {
        // The bus is lost when the worker dies, but pending_inputs
        // (Postgres) survives. After resume, the queued message is
        // drained into the resumed turn (or the next one).
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-resume-pending',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'chat-slow', __TEST_CHAT_SLEEP_MS: '1500' },
        })
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'first' } })
        const sessionId = run.body.sessionId as string
        await waitForAwaitingInput(cluster, sessionId, { afterTurn: 1, timeoutMs: 15_000 })

        // Wake turn 2 with a /send, wait for it to start running.
        await send(cluster, app.slug, sessionId, 'second', { pat: TEAM_SECRET })
        await waitForStatus(cluster, sessionId, ['running'], { timeoutMs: 5_000 })

        // Queue another message while the worker is mid-turn — lands in
        // pending_inputs (column). Then crash.
        await send(cluster, app.slug, sessionId, 'queued-during-crash', { pat: TEAM_SECRET })
        const mid = await readSessionRow(cluster, sessionId)
        expect(mid?.pendingInputsColumn.map((p) => p.content)).toContain('queued-during-crash')
        await simulateWorkerCrash(sessionId)

        // Whoever picks the row up next sees pending_inputs (still
        // carrying BOTH 'second' and 'queued-during-crash' because
        // the dead worker's commit never landed) and the persisted
        // state from turn 1. Both messages flow into state.messages
        // exactly once — at-least-once delivery is preserved because
        // the dequeue snapshots rather than drains.
        const start = Date.now()
        while (Date.now() - start < 15_000) {
            const row = await readSessionRow(cluster, sessionId)
            const userMsgs = row?.state?.messages.filter((m) => m.role === 'user').map((m) => m.content) ?? []
            if (userMsgs.length >= 3) {
                expect(userMsgs.filter((m) => m === 'first')).toHaveLength(1)
                expect(userMsgs.filter((m) => m === 'second')).toHaveLength(1)
                expect(userMsgs.filter((m) => m === 'queued-during-crash')).toHaveLength(1)
                return
            }
            await new Promise((r) => setTimeout(r, 100))
        }
        throw new Error('worker-resume: did not see all three user messages within 15s')
    })
})
