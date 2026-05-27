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
import {
    cancel,
    post,
    readSessionRow,
    readSessionStatus,
    send,
    waitForAwaitingInput,
    waitForStatus,
} from '../../harness/clients'
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-chat-edges-team-secret'

describe('persistent-chat: lifecycle edges', () => {
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
        const sessionId = run.body.sessionId as string

        // Wait for the worker to park after turn 1's awaiting_input outcome.
        await waitForAwaitingInput(cluster, sessionId, { afterTurn: 1 })

        const cancelRes = await cancel(cluster, app.slug, sessionId, { pat: TEAM_SECRET })
        expect(cancelRes.status).toBe(202)

        // Ingress walked the direct cancellation path:
        // `queue.cancelIfParked` flipped status=available → canceled in
        // a single UPDATE. The bus also got a synthetic
        // session_failed event so /listen subscribers see a terminal
        // signal even though no worker ran the cancel branch.
        await waitForStatus(cluster, sessionId, ['canceled'], { timeoutMs: 5_000 })
        expect(await readSessionStatus(cluster, sessionId)).toBe('canceled')
    })

    it('cancel of a terminal (completed) session: idempotent 202', async () => {
        // Completed → cancel is a no-op acknowledgement. Beats 409
        // for clients that retry on transient errors.
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-cancel-terminal',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'chat-once' },
        })
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'done' } })
        const sessionId = run.body.sessionId as string
        await waitForStatus(cluster, sessionId, ['completed'])

        const res = await cancel(cluster, app.slug, sessionId, { pat: TEAM_SECRET })
        expect(res.status).toBe(202)
        expect(await readSessionStatus(cluster, sessionId)).toBe('completed')
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

        await waitForStatus(cluster, sessionId, ['completed'])
        const followup = await send(cluster, app.slug, sessionId, 'too late', { pat: TEAM_SECRET })
        expect(followup.status).toBe(410)
        expect(followup.body.error).toMatch(/session terminated|session is completed/i)

        // No new pendingInputs row landed — the manager's append
        // rolled back when it saw the terminal status.
        const row = await readSessionRow(cluster, sessionId)
        expect(row?.pendingInputsColumn).toHaveLength(0)
    })

    it('/send to a failed session → 410 Gone', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-send-after-failed',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'failure' },
        })
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'oops' } })
        const sessionId = run.body.sessionId as string
        await waitForStatus(cluster, sessionId, ['failed'])

        const res = await send(cluster, app.slug, sessionId, 'are you ok', { pat: TEAM_SECRET })
        expect(res.status).toBe(410)
    })

    it('/send to a nonexistent session id → 404', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-send-404',
            auth: { type: 'pat' },
        })
        const res = await send(cluster, app.slug, '00000000-0000-0000-0000-000000000000', 'hi', { pat: TEAM_SECRET })
        // The /send ingress path strict-matches the principal BEFORE
        // looking at the session row, so an unknown id surfaces from
        // `queue.getPrincipal` returning `undefined`. The ingress
        // returns 404 in that branch.
        expect(res.status).toBe(404)
    })
})
