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
import { post, waitForAwaitingInput } from '../../harness/clients'
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

    it('runs through the real SDK against the mock, parks at awaiting_input, echoes the user message', async () => {
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

        // Turn-by-turn: the SDK completes ONE assistant message and
        // the executor returns `awaiting_input`. The queue row parks
        // at status=available with state.turnCount=1, waiting for the
        // next `/send` (or end_session) to advance.
        const row = await waitForAwaitingInput(cluster, sessionId, { afterTurn: 1, timeoutMs: 30_000 })
        expect(row.state?.turnCount).toBe(1)

        // The mock saw exactly one /v1/messages request from the SDK,
        // with model: 'mock-echo' and the POSTed body content as the
        // latest user message.
        const requests = mock.requests()
        expect(requests.length).toBeGreaterThanOrEqual(1)
        const last = requests[requests.length - 1]
        expect(last.model).toBe('mock-echo')
        const userMessages = last.messages.filter((m) => m.role === 'user')
        const userText = userMessages.flatMap((m) => extractText(m.content)).join(' ')
        expect(userText).toContain('hello mock')

        // The assistant's reply (the echo) made it back through bridge
        // → session_logger → ClickHouse.
        await cluster.clickhouse.waitForLogs(
            sessionId,
            (r) => r.some((row) => row.message.startsWith('[chat] assistant:') && row.message.includes('hello mock')),
            { timeoutMs: 15_000 }
        )
    }, 60_000)
})

function extractText(content: unknown): string[] {
    if (typeof content === 'string') {
        return [content]
    }
    if (Array.isArray(content)) {
        return content.flatMap((b) => {
            if (b && typeof b === 'object') {
                const block = b as Record<string, unknown>
                if (block.type === 'text' && typeof block.text === 'string') {
                    return [block.text]
                }
            }
            return []
        })
    }
    return []
}
