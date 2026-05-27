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
import { post, send } from '../../harness/clients'
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-chat-queue-team-secret'

describe.skip('persistent-chat: queued follow-ups during an in-flight turn', () => {
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
            auth: { type: 'pat' },
            // chat-slow: holds the turn for ~3s, then echoes + awaiting_input.
            encryptedEnv: { __TEST_EXECUTOR: 'chat-slow' },
        })

        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'first' } })
        const sessionId = run.body.sessionId as string

        // Send a follow-up while turn 1 is still running.
        // TODO: helper `waitForStatus(running)` + a tiny additional beat
        // to ensure we're inside the executor's body.
        const followup = await send(cluster, app.slug, sessionId, 'queue me', { pat: TEAM_SECRET })
        expect(followup.status).toBe(202)

        // Even DURING the turn, the message must be visible in pendingInputs.
        // This is the load-bearing assertion: durability is in Postgres,
        // not in the worker's memory.
        // const stateMid = await readSessionState(cluster, sessionId)
        // expect(stateMid.pendingInputs.map(p => p.content)).toContain('queue me')

        // Turn 1 finishes, turn 2 picks up the pending input.
        // const stateEnd = await readSessionState(cluster, sessionId)
        // expect(stateEnd.pendingInputs).toHaveLength(0)
        // expect(stateEnd.messages.find(m => m.role === 'user' && m.content === 'queue me')).toBeDefined()
    })

    it('three /sends mid-turn → pendingInputs[] has all three in arrival order', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-queue-three',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'chat-slow' },
        })

        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'go' } })
        const sessionId = run.body.sessionId as string

        await send(cluster, app.slug, sessionId, 'one', { pat: TEAM_SECRET })
        await send(cluster, app.slug, sessionId, 'two', { pat: TEAM_SECRET })
        await send(cluster, app.slug, sessionId, 'three', { pat: TEAM_SECRET })

        // All three visible while turn 1 still runs.
        // const mid = await readSessionState(cluster, sessionId)
        // expect(mid.pendingInputs.map(p => p.content)).toEqual(['one', 'two', 'three'])

        // After turn 1 ends, the executor drains all three. The spec
        // decision: do they become THREE user messages (one per turn)
        // or ONE concatenated user message? Pin whichever we choose.
        // First pass: each pending input is its own turn.
        //
        // const end = await readSessionState(cluster, sessionId)
        // const userMessages = end.messages.filter(m => m.role === 'user').map(m => m.content)
        // expect(userMessages).toEqual(['go', 'one', 'two', 'three'])
    })

    it('a /send that arrives BEFORE the worker has dequeued the job is still durable', async () => {
        // The Redis bus has no subscriber yet — but Postgres takes the
        // write regardless. When the worker eventually picks the job
        // up it sees the pendingInputs already there.
        // TODO: this is the race the bus-only model failed on. Worth
        // its own case so a regression doesn't silently break it.
    })
})
