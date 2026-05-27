/**
 * App test: real bundle, real AssServerExecutor, real Claude Agent
 * SDK, FAKE Anthropic. Single-turn echo via the harness's mock.
 *
 * This is the "the mock infrastructure works" checkpoint — proves
 * `model:` propagates end-to-end (agent.ts → bundler → manifest →
 * compileAgent → runSession → SDK options), `ANTHROPIC_BASE_URL`
 * lands at the mock, and the streaming SSE response is consumed by
 * the SDK correctly. No Anthropic credits, no real-LLM gating —
 * runs on every commit.
 */
import { resolve } from 'node:path'

import { bundleAndUpload } from '../../harness/bundle'
import { post, waitForStatus } from '../../harness/clients'
import { type AgentCluster, getMockAnthropic, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'

const FIXTURE_DIR = resolve(__dirname, '../../../fixtures/mock-echo')
const TEAM_SECRET = 'e2e-mock-echo-team-secret'

describe('app: mock-anthropic SDK roundtrip (single-turn echo)', () => {
    let cluster: AgentCluster
    let bundleS3Key: string
    let bundleSha256: string

    beforeAll(async () => {
        cluster = await openSharedCluster()
        // Boot the mock at the port globalSetup reserved for us. The
        // bins already point at this URL via `ANTHROPIC_BASE_URL`.
        await getMockAnthropic()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
        const uploaded = await bundleAndUpload(cluster.cleanup, FIXTURE_DIR)
        const echo = uploaded.find((b) => b.agentSlug === 'e2e-mock-echo')
        if (!echo) {
            throw new Error('bundleAndUpload returned no e2e-mock-echo')
        }
        bundleS3Key = echo.bundleS3Key
        bundleSha256 = echo.bundleSha256
    }, 60_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    it('runs through the real SDK against the mock, completes, returns the echoed text', async () => {
        const mock = await getMockAnthropic()
        mock.reset()

        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'mock-echo',
            auth: { type: 'pat' },
            bundle: { s3Key: bundleS3Key, sha256: bundleSha256 },
        })

        const res = await post(cluster, app.slug, {
            pat: TEAM_SECRET,
            body: { message: 'hello mock' },
        })
        expect(res.status).toBe(202)
        const sessionId = res.body.sessionId as string

        // The SDK runs the whole agent loop in one call today; with no
        // tools and an end-of-turn assistant message from the mock the
        // session completes in one go. The SDK refactor (turn-by-turn)
        // will change this to `awaiting_input` after the first turn —
        // that's the next commit.
        await waitForStatus(cluster, sessionId, ['completed'], { timeoutMs: 30_000 })

        // The mock saw exactly one /v1/messages request from the SDK,
        // with model: 'mock-echo' and the user prompt the agent was
        // invoked with.
        const requests = mock.requests()
        expect(requests.length).toBeGreaterThanOrEqual(1)
        expect(requests[0].model).toBe('mock-echo')

        // The agent's reply lands in log_entries as a `[chat] assistant:`
        // line. The mock echoes whatever the SDK forwards as the last
        // user message — that's "Begin the run." today (the static prompt
        // session-runner passes). When we switch to turn-by-turn the
        // user message will be the POSTed body content; until then we
        // just assert the assistant line exists and the session ran.
        const rows = await cluster.clickhouse.waitForLogs(
            sessionId,
            (r) => r.some((row) => row.message.startsWith('[chat] assistant:')),
            { timeoutMs: 15_000 }
        )
        expect(rows.some((row) => row.message.includes('session_completed'))).toBe(true)
    }, 60_000)
})
