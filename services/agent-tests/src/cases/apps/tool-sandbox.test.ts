/**
 * App test: a tool-using agent driven through the production Docker tool
 * sandbox.
 *
 * Extends the greeting-bot test with the part that one couldn't reach
 * — a locally-defined custom tool. The agent has one tool (`magic.summon`)
 * that returns a fixed nonce string the model would never guess. Asserting
 * the nonce appears in the final assistant message proves the tool
 * actually executed inside the sandbox; asserting the `[tool] mcp__ass__…`
 * line landed in ClickHouse proves the tool_call event flowed all the
 * way through bridge → bus → session_logger → Kafka → CH.
 *
 * Two extra assertions vs. the greeting test:
 *   1. log_entries contains `[tool] mcp__ass__magic__summon` — the runner
 *      registered the tool and the SDK fired it.
 *   2. `agent_stack_agentapplicationsandboxinstance` has a row attributed
 *      to this revision that reached state=`terminated` — the durable
 *      SandboxTracker walked the lifecycle on acquire + release.
 *
 * Like the greeting test this requires `AGENT_E2E_REAL_LLM=1` + a key.
 * It additionally requires Docker to be running locally; the bundled
 * runner picks the Docker provider by default and the sandbox container
 * is built lazily on first acquire.
 */
import { resolve } from 'node:path'

import { bundleAndUpload } from '../../harness/bundle'
import { chatFlow } from '../../harness/chat'
import { type AgentCluster, startCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'
import { DEFAULT_TEST_MODEL, REAL_LLM, describeRealLlm } from '../../harness/llm'

const FIXTURE_DIR = resolve(__dirname, '../../../fixtures/tooly')

const TEAM_SECRET = 'e2e-app-tooly-team-secret'
const MAGIC_WORD = 'XYZZY-2718-PLUGH'

describeRealLlm('app: tool-using agent (custom tool runs through DockerToolSandbox)', () => {
    let cluster: AgentCluster
    let bundleS3Key: string
    let bundleSha256: string

    beforeAll(async () => {
        if (!REAL_LLM) {
            return
        }

        cluster = await startCluster({
            executor: 'sdk',
            env: {
                ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY ?? '',
                ANTHROPIC_MODEL: DEFAULT_TEST_MODEL,
                // Pin the sandbox provider so the test fails fast and clearly
                // if Docker isn't running — beats waiting for Modal creds to
                // get auto-selected and then erroring on "not implemented".
                AGENT_RUNNER_TOOL_SANDBOX: 'docker',
            },
        })
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)

        const uploaded = await bundleAndUpload(cluster.cleanup, FIXTURE_DIR)
        const tooly = uploaded.find((b) => b.agentSlug === 'e2e-tooly')
        if (!tooly) {
            throw new Error('bundleAndUpload returned no e2e-tooly')
        }
        bundleS3Key = tooly.bundleS3Key
        bundleSha256 = tooly.bundleSha256
    }, 120_000)

    afterAll(async () => {
        if (!cluster) {
            return
        }
        await cluster.cleanup.runAll()
        await cluster.stop()
    }, 60_000)

    it('calls a sandboxed custom tool and threads its output back to the user + log_entries + SandboxInstance', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'app-tooly',
            auth: { type: 'pat' },
            bundle: { s3Key: bundleS3Key, sha256: bundleSha256 },
        })

        const chat = chatFlow(cluster, app.slug, {
            pat: TEAM_SECRET,
            firstMessage: 'Tell me the magic word.',
            // Sandbox warm-up (image build on first run) is the long pole.
            waitTimeoutMs: 120_000,
        })

        // 1. The model called the tool and copied its output into the reply.
        const reply = await chat.waitForReply()
        expect(reply.text).toContain(MAGIC_WORD)

        await chat.waitForCompletion()

        // 2. The tool_call event made it all the way to ClickHouse with the
        //    expected MCP namespaced name — proves bridge + log_entries.
        const sessionId = await chat.sessionId
        const rows = await cluster.clickhouse.logsForSession(sessionId)
        const toolLines = rows.filter((r) => r.message.startsWith('[tool] '))
        expect(toolLines.some((r) => r.message.includes('mcp__ass__magic__summon'))).toBe(true)

        // 3. The durable SandboxInstance row was created AND walked to
        //    `terminated` when the sandbox released. Filtering by the
        //    revision keeps this test independent of any concurrent sessions
        //    elsewhere in the local cluster.
        const sandboxRows = await cluster.posthog.query<{ state: string }>(
            `SELECT state
             FROM agent_stack_agentapplicationsandboxinstance
             WHERE revision_id = $1
             ORDER BY created_at`,
            [app.revisionId]
        )
        expect(sandboxRows.rows.length).toBeGreaterThan(0)
        expect(sandboxRows.rows.every((r) => r.state === 'terminated')).toBe(true)
    }, 180_000)
})
