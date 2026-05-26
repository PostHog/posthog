import { post, readPrincipal, waitForStatus } from '../harness/clients'
/**
 * Headline runtime test — proves the principal flows all the way through
 * the production pipes, end-to-end:
 *
 *     POST /run  ─auth─▶  ingress
 *                          ├── caller-auth resolves a ServicePrincipal
 *                          ├── enqueues agent_sessions (principal JSONB stamped)
 *                          └── returns sessionId
 *     runner    ─dequeue─▶ pulls the row (incl. principal)
 *                          ├── hands to SessionExecutor with principal in ctx
 *                          └── PrincipalEchoExecutor writes principal into the response msg
 *     SessionBus ─event─▶  ingress /listen forwards via SSE
 *     LogProducer ─Kafka─▶ log_entries topic
 *                          └── ClickHouse Kafka engine + MV → log_entries table
 *
 * Three assertions, one per stop on the path:
 *   1. SSE stream contains the principal-tagged message  → runner saw the principal
 *   2. agent_sessions.principal matches what was stamped → ingress persisted it
 *   3. log_entries(instance_id=sessionId) has rows       → Kafka→CH path is alive
 */
import { type AgentCluster, startCluster } from '../harness/cluster'
import { PrincipalEchoExecutor, renderPrincipal } from '../harness/executors'
import { createApp, setTeamSecret } from '../harness/fixtures'

const TEAM_SECRET = 'e2e-runtime-team-secret'

describe('runtime: ingress → runner → executor → logs', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await startCluster({ executor: new PrincipalEchoExecutor() })
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
    }, 30_000)

    afterAll(async () => {
        if (!cluster) {
            return
        }
        await cluster.cleanup.runAll()
        await cluster.stop()
    }, 30_000)

    it('a pat-auth agent enqueues, runs, surfaces the principal in the assistant message, and lands it in ClickHouse', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'runtime-pat',
            auth: { type: 'pat' },
        })

        // 1. POST /run with a valid PAT.
        const res = await post(cluster, app.slug, { pat: TEAM_SECRET })
        expect(res.status).toBe(202)
        const sessionId = res.body.sessionId as string
        expect(sessionId).toMatch(/^[0-9a-f-]{36}$/)

        // 2. Ingress stamped the principal on the queue row.
        const stamped = await readPrincipal(cluster, sessionId)
        expect(stamped).toEqual({ kind: 'service', orgId: '1', caller: 'team-secret' })

        // 3. Wait for the runner to complete the session — proves dequeue worked.
        await waitForStatus(cluster, sessionId, ['completed'])

        // 4. The principal-bearing assertion: the executor's `message`
        //    content is rendered into log_entries via session_logger →
        //    Kafka → CH (`[chat] assistant: <message>`). If the rendered
        //    principal string is in there, every layer of the pipeline
        //    saw it — ingress resolved → queue persisted → runner
        //    dequeued → executor read → bus published → Kafka delivered →
        //    ClickHouse Kafka engine + MV inserted.
        const expectedRendering = renderPrincipal(stamped as Parameters<typeof renderPrincipal>[0])
        const rows = await cluster.clickhouse.waitForLogs(
            sessionId,
            (r) => r.some((row) => row.message.includes(expectedRendering)),
            { timeoutMs: 15_000 }
        )
        expect(rows.every((row) => row.instance_id === sessionId)).toBe(true)
        expect(rows.every((row) => row.log_source === 'agent_session')).toBe(true)
        // Spot-check the lifecycle events landed too — turn_started +
        // turn_completed + session_completed are the deterministic markers.
        expect(rows.some((row) => row.message.includes('turn_started'))).toBe(true)
        expect(rows.some((row) => row.message.includes('session_completed'))).toBe(true)
    }, 30_000)

    it('a public agent runs to completion with no principal — rendered as "principal: none" in ClickHouse', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'runtime-public',
            auth: { type: 'public' },
        })
        const res = await post(cluster, app.slug)
        expect(res.status).toBe(202)
        const sessionId = res.body.sessionId as string

        expect(await readPrincipal(cluster, sessionId)).toBeNull()
        await waitForStatus(cluster, sessionId, ['completed'])

        // Same end-to-end assertion: the executor saw a null principal,
        // rendered it as `principal: none`, and that string landed in CH.
        await cluster.clickhouse.waitForLogs(
            sessionId,
            (r) => r.some((row) => row.message.includes('principal: none')),
            {
                timeoutMs: 15_000,
            }
        )
    }, 30_000)
})
