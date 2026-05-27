/**
 * Cases 6 & 7: terminal-state edges.
 *
 * Today: `/cancel` works for a running session (case in
 * `cancel.test.ts`). The semantics for a PARKED session (awaiting
 * input) aren't defined. `/send` to a `completed` session returns 202
 * and is silently dropped — same false-positive bug as mid-cycle.
 *
 * Spec contracts:
 *   - `/cancel` on a parked session: terminal `canceled` status,
 *     `session_failed` log entry "cancelled by client", binding (if
 *     any) cleared, pendingInputs discarded.
 *   - `/send` to a terminal session (completed/failed/canceled) ->
 *     HTTP 410 Gone, body `{ error: 'session terminated' }`. Not 202.
 *     The client can decide to start a new session.
 *   - `/send` to a nonexistent session id -> 404.
 *   - `/cancel` to a terminal session -> 409 Conflict (idempotent
 *     might be nicer; pin the choice).
 */
import { post, send } from '../../harness/clients'
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-chat-edges-team-secret'

describe.skip('persistent-chat: lifecycle edges', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
    }, 30_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    it('cancel of a parked-awaiting-input session: terminal canceled + session_failed log', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-cancel-parked',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'chat-echo' },
        })
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'hi' } })
        const _sessionId = run.body.sessionId as string

        // After turn 1 the chat-echo executor parks awaiting_input.
        // TODO: waitForAwaitingInput(cluster, _sessionId)

        // /cancel on a PARKED session — different code path than
        // /cancel mid-LLM (no bus subscriber to interrupt).
        // The worker isn't actively holding the job; the queue row
        // sits with status=available and scheduled_at in the future.
        // We need the cancel to:
        //   - flip status to `canceled` synchronously (the worker
        //     isn't there to do it lazily)
        //   - emit session_failed via the bus / log_entries
        //   - delete the parked job from the queue (so it won't
        //     resurrect on the next sweep)
        //
        // TODO: const cancelRes = await cancel(cluster, app.slug, sessionId, { pat: TEAM_SECRET })
        // expect(cancelRes.status).toBe(202)
        // expect(await readSessionStatus(cluster, sessionId)).toBe('canceled')

        // The cancel log entry uses the same "cancelled by client"
        // string as mid-LLM cancel — keep it consistent for ops.
        // const rows = await cluster.clickhouse.waitForLogs(sessionId,
        //   r => r.some(row => row.message.includes('cancelled by client')))
        // expect(rows.some(r => r.message.includes('session_failed'))).toBe(true)
    })

    it('/send to a completed session → 410 Gone (not 202)', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-send-after-complete',
            auth: { type: 'pat' },
            // chat-once: returns `completed` immediately (no parking).
            encryptedEnv: { __TEST_EXECUTOR: 'chat-once' },
        })
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'go' } })
        const sessionId = run.body.sessionId as string

        // TODO: await waitForStatus(cluster, sessionId, ['completed'])
        const followup = await send(cluster, app.slug, sessionId, 'too late', { pat: TEAM_SECRET })
        expect(followup.status).toBe(410)
        expect(followup.body.error).toMatch(/session terminated|session is completed/i)

        // No new pendingInputs row.
        // const state = await readSessionState(cluster, sessionId)
        // expect(state.pendingInputs).toHaveLength(0)
    })

    it('/send to a failed session → 410 Gone', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-send-after-failed',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'failure' },
        })
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'oops' } })
        const sessionId = run.body.sessionId as string
        // TODO: await waitForStatus(cluster, sessionId, ['failed'])

        const res = await send(cluster, app.slug, sessionId, 'are you ok', { pat: TEAM_SECRET })
        expect(res.status).toBe(410)
    })

    it('/send to a canceled session → 410 Gone', async () => {
        // Same as failed; pin it explicitly so we don't accidentally
        // treat canceled as resumeable.
    })

    it('/send to a nonexistent session id → 404', async () => {
        // const res = await send(cluster, app.slug, '00000000-0000-0000-0000-000000000000', 'hi', { pat: TEAM_SECRET })
        // expect(res.status).toBe(404)
    })

    it('/cancel of an already-terminal session → 409 Conflict (or 202 idempotent — pin)', async () => {
        // Implementer choice: rejecting feels surprising to the client
        // who might be retrying. Idempotent-202 is friendlier. Pin
        // whichever; consistency matters more than the verdict.
    })
})
