/**
 * /cancel runtime e2e.
 *
 * Drives the full cancellation pipeline against a real cluster:
 *
 *   POST /run  ─auth─▶ ingress enqueues the session, runner picks it up
 *                       and hands it to the `slow-cancellable` test executor
 *                       which subscribes to bus.subscribeInput and sleeps.
 *   POST /cancel/:id ─auth─▶ ingress writes a `cancel` to the bus input
 *                       channel; the executor observes it, exits with
 *                       `kind: 'cancelled'`, the worker walks the
 *                       cancellation branch (`session_failed` event with
 *                       `error: 'cancelled by client'`, `job.cancel()`).
 *
 * Three assertions per stop:
 *   1. /cancel returns 202.
 *   2. The queue row reaches `canceled` status.
 *   3. ClickHouse has the `cancelled by client` line + a `session_failed`
 *      lifecycle event — proves the worker's cancel branch ran end to end.
 */
import supertest from 'supertest'

import { hostFor, post, readSessionStatus, waitForStatus } from '../../harness/clients'
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-cancel-team-secret'

describe('/cancel runtime e2e', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
    }, 30_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    it('a /cancel during a slow turn lands the session in `canceled` with a session_failed("cancelled by client") log line', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'cancel-pat',
            auth: { type: 'pat' },
            // Routes the shared runner to the slow-cancellable executor —
            // that's the one that subscribes to bus.subscribeInput and
            // observes the cancel signal we send below.
            encryptedEnv: { __TEST_EXECUTOR: 'slow-cancellable' },
        })

        const run = await post(cluster, app.slug, { pat: TEAM_SECRET })
        expect(run.status).toBe(202)
        const sessionId = run.body.sessionId as string

        // Wait for the worker to dequeue and the executor to subscribe
        // before we /cancel. Redis pub-sub has no replay, so a cancel
        // delivered before the executor's `subscribeInput` would be
        // silently dropped and the test would hang. The 10s budget is
        // intentionally generous — first-job pickup after spawn is the
        // slowest pickup the runner ever does in a test.
        await waitForStatus(cluster, sessionId, ['running'], { timeoutMs: 10_000 })
        // Tiny extra beat so the executor's `subscribeInput` settles
        // before we publish — status flips to running BEFORE the worker
        // calls runTurn (and runTurn's first await is the subscribe).
        await new Promise((r) => setTimeout(r, 100))

        const cancelRes = await supertest(cluster.ingressUrl)
            .post(`/cancel/${sessionId}`)
            .set('x-original-host', hostFor(app.slug))
            .set('authorization', `Bearer ${TEAM_SECRET}`)
            .send({})
        expect(cancelRes.status).toBe(202)

        await waitForStatus(cluster, sessionId, ['canceled'], { timeoutMs: 15_000 })
        expect(await readSessionStatus(cluster, sessionId)).toBe('canceled')

        const rows = await cluster.clickhouse.waitForLogs(
            sessionId,
            (r) => r.some((row) => row.message.includes('cancelled by client')),
            { timeoutMs: 15_000 }
        )
        // Lifecycle event landed too — the cancel branch in worker.ts maps
        // to a terminal `session_failed` envelope in the bus union.
        expect(rows.some((r) => r.message.includes('session_failed'))).toBe(true)
    }, 30_000)
})
