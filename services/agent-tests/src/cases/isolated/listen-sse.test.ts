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
import { type AgentCluster, startCluster } from '../../harness/cluster'
import { createApp } from '../../harness/fixtures'

describe('/listen SSE e2e', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await startCluster({ executor: 'slow-cancellable' })
    }, 30_000)

    afterAll(async () => {
        if (!cluster) {
            return
        }
        await cluster.cleanup.runAll()
        await cluster.stop()
    }, 30_000)

    it('streams the run lifecycle as SSE events terminating in session_completed', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'listen-public',
            auth: { type: 'public' },
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
        const message = events.find((e) => e.event === 'message')
        expect(JSON.stringify(message?.data ?? {})).toContain('slow-cancellable')

        await waitForStatus(cluster, sessionId, ['completed'])
    }, 30_000)
})
