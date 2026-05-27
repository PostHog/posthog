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
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-chat-resume-team-secret'

describe.skip('persistent-chat: worker crash mid-session resumes cleanly', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
    }, 30_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    it('killing the runner between turns preserves state; a fresh runner picks up and continues', async () => {
        // This test needs a private runner subprocess we can SIGKILL.
        // The shared-cluster runner is owned by globalSetup and we
        // mustn't kill it. Options:
        //   (a) Spawn an isolated runner with `spawnBins` for this suite
        //       only and leave the shared ingress alone.
        //   (b) Add a `restartRunner()` capability to the shared cluster
        //       (gnarlier; affects every other suite in the same run).
        // (a) is cleaner. The harness's `spawnBins({ executor: 'router' })`
        // gives us our own runner pid; we can SIGKILL it directly.
        // 1. Create a session, run turn 1 with chat-echo, observe parked
        //    `awaiting_input` status.
        // 2. SIGKILL the isolated runner subprocess.
        // 3. Wait for the queue janitor to mark the job's lease expired
        //    and flip it back to `available`. (Today's janitor handles
        //    this — heartbeat expiry → `available`.)
        // 4. Spawn a fresh runner.
        // 5. POST /send. Assert turn 2 lands.
        // 6. Read state.messages: turn 1's assistant message is still
        //    there (didn't dissolve with the dead runner).
        //
        // TODO: spawnBinsOptions to include just the runner (not
        // ingress). The shared ingress points at the same queue, so it
        // doesn't care which runner is alive.
    })

    it('killing the runner DURING an in-flight LLM call: the partial assistant message is discarded; turn replays cleanly', async () => {
        // Define the "at-most-once side effects, at-least-once
        // resumption" contract: an LLM call that died mid-stream is
        // replayed from the last successful turn boundary. The user
        // sees one assistant message, not a torn one.
        //
        // This is where the SDK's own resume semantics matter — if we
        // give it the same sessionId twice, does it dedupe? Spec it
        // before we test it.
    })

    it('multiple /send messages arrive while the runner is dead — all preserved and drained on resume', async () => {
        // Combines case 3 with case 4. Bus is unavailable but Postgres
        // writes still succeed. When the new runner starts, all pending
        // inputs are visible.
    })
})
