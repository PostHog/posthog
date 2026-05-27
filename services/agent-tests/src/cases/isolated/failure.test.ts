import { post, readSessionStatus, waitForStatus } from '../../harness/clients'
/**
 * Session failure-path e2e.
 *
 * Runs a session against the `failure` test executor (always returns
 * `{ kind: 'failed', error }`) and asserts the full failure pipeline:
 *
 *   - the queue row lands in `failed` status (worker `job.fail()`)
 *   - the bus / log_entries pipeline carries a terminal `session_failed`
 *     event with the executor-provided error string
 *
 * This is the partner to the "completed" path in runtime.test.ts — the
 * production worker has a dedicated failure branch and it was previously
 * uncovered end to end.
 */
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-failure-team-secret'
const FAILURE_MESSAGE = 'forced failure for e2e test'

describe('runtime failure path', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
    }, 30_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    it('an executor returning `kind: failed` walks through to a `failed` queue row + `session_failed` log entry', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'failure-pat',
            auth: { type: 'pat' },
            encryptedEnv: { __TEST_EXECUTOR: 'failure' },
        })

        const res = await post(cluster, app.slug, { pat: TEAM_SECRET })
        expect(res.status).toBe(202)
        const sessionId = res.body.sessionId as string

        await waitForStatus(cluster, sessionId, ['failed'], { timeoutMs: 15_000 })
        expect(await readSessionStatus(cluster, sessionId)).toBe('failed')

        // The lifecycle event landed: error message AND the session_failed
        // line shape (formatEvent: `[error] session_failed: <error>`).
        const rows = await cluster.clickhouse.waitForLogs(
            sessionId,
            (r) => r.some((row) => row.message.includes(FAILURE_MESSAGE)),
            { timeoutMs: 15_000 }
        )
        expect(rows.some((r) => r.message.includes('session_failed'))).toBe(true)
        expect(rows.some((r) => r.level === 'ERROR')).toBe(true)
    }, 30_000)
})
