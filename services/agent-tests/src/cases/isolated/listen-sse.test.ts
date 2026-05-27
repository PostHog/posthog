import { collectSse, post, waitForStatus } from '../../harness/clients'
/**
 * /listen SSE e2e.
 *
 * Subscribes to the SSE stream for a freshly-started session and asserts
 * the runner publishes its lifecycle events live over the bus. Uses the
 * `slow-cancellable` executor (sleeps before completing) so the test has
 * a deterministic window in which to attach `/listen` before the session
 * finishes — `RedisSessionBus` has no replay, so a fast-completing
 * executor would race the subscriber.
 *
 * The full event arc we expect:
 *   - turn_started   (worker, pre-executor)
 *   - turn_completed (worker, post-executor)
 *   - message        (worker, after the executor returns `completed`)
 *   - session_completed (worker, terminal)
 *
 * `collectSse` closes the connection as soon as it sees `session_completed`
 * — no need for a separate timeout/teardown.
 */
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp } from '../../harness/fixtures'

describe('/listen SSE e2e', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await openSharedCluster()
    }, 30_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    it('streams the run lifecycle as SSE events terminating in session_completed', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'listen-public',
            auth: { type: 'public' },
            // Use the slow-cancellable executor so the runner sleeps long
            // enough for the SSE subscriber to attach before the events
            // start flowing (Redis pubsub has no replay).
            encryptedEnv: { __TEST_EXECUTOR: 'slow-cancellable' },
        })

        const run = await post(cluster, app.slug)
        expect(run.status).toBe(202)
        const sessionId = run.body.sessionId as string

        // SSE collector subscribes to /listen and returns when it sees a
        // terminal event. The executor sleeps long enough for this to
        // attach before the runner emits turn_completed.
        const events = await collectSse(cluster, app.slug, sessionId, { timeoutMs: 20_000 })

        const eventNames = events.map((e) => e.event)
        expect(eventNames).toContain('turn_started')
        expect(eventNames).toContain('turn_completed')
        expect(eventNames).toContain('message')
        expect(eventNames).toContain('session_completed')

        // The assistant message body the executor emitted should be on
        // the wire too — proves the SSE encoder serialised the payload.
        // The worker now also publishes the user-side initial-input
        // message, so filter to `role: 'assistant'` events specifically.
        const assistantMessage = events.find(
            (e) => e.event === 'message' && (e.data as { role?: string })?.role === 'assistant'
        )
        expect(JSON.stringify(assistantMessage?.data ?? {})).toContain('slow-cancellable')

        await waitForStatus(cluster, sessionId, ['completed'])
    }, 30_000)
})
