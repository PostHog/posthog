/**
 * App test: a real two-turn greeting flow against Claude Haiku 4.5.
 *
 * What this exercises that the isolated tests don't:
 *   - `ass-bundler` actually bundles `fixtures/greeting/` (TS compile → tar)
 *   - The bundle is uploaded to the local MinIO via the real S3 client
 *   - `AssServerExecutor` (the prod executor) downloads + extracts it,
 *     loads via `loadCompiledAgent`, drives `runSession` from ass-server
 *   - The Claude Agent SDK actually runs against Anthropic with the
 *     bundled system prompt
 *   - The model's first reply triggers a `/send` follow-up; the second
 *     turn picks up where the first left off
 *   - The full chat lands in `log_entries` and we read the assistant
 *     messages back to assert
 *
 * Loose assertions on the reply text (LLMs are non-deterministic). The
 * fixture's system prompt locks the model into a tight script — we still
 * use case-insensitive substring / regex.
 */
import { resolve } from 'node:path'

import { bundleAndUpload } from '../../harness/bundle'
import { chatFlow } from '../../harness/chat'
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'
import { REAL_LLM, describeRealLlm } from '../../harness/llm'

// Path to the fixture project. Bundling compiles its TS so the path needs
// to point at the source tree (not dist) regardless of where jest runs from.
const FIXTURE_DIR = resolve(__dirname, '../../../fixtures/greeting')

const TEAM_SECRET = 'e2e-app-greeting-team-secret'

describeRealLlm('app: greeting bot (real Claude, two-turn chat)', () => {
    let cluster: AgentCluster
    let bundleS3Key: string
    let bundleSha256: string

    beforeAll(async () => {
        if (!REAL_LLM) {
            return
        }

        // Shared runner is started with ANTHROPIC_API_KEY by globalSetup.
        // Apps with no `__TEST_EXECUTOR` marker fall through to the real
        // SDK executor — exactly what this test wants.
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)

        const uploaded = await bundleAndUpload(cluster.cleanup, FIXTURE_DIR)
        const greeter = uploaded.find((b) => b.agentSlug === 'e2e-greeter')
        if (!greeter) {
            throw new Error('bundleAndUpload returned no e2e-greeter')
        }
        bundleS3Key = greeter.bundleS3Key
        bundleSha256 = greeter.bundleSha256
    }, 60_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    it('asks for the user name on the first turn, then greets the name on the second', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'app-greeting',
            auth: { type: 'pat' },
            bundle: { s3Key: bundleS3Key, sha256: bundleSha256 },
        })

        const chat = chatFlow(cluster, app.slug, {
            pat: TEAM_SECRET,
            firstMessage: 'Hello!',
            waitTimeoutMs: 60_000,
        })

        // Turn 1 — the agent calls `ask_for_input` to pause. The prompt is
        // the user-facing "first reply"; loose substring match because the
        // model wraps it in whatever phrasing it picks.
        const ask = await chat.waitForAwaitingInput()
        expect((ask.prompt ?? '').toLowerCase()).toContain('name')

        // Turn 2 — provide a name, expect a greeting that includes it.
        const NAME = 'Quentin'
        await chat.send(NAME)
        const greeting = await chat.waitForReply()
        expect(greeting.text).toMatch(new RegExp(NAME, 'i'))
        expect(greeting.text.toLowerCase()).toContain('welcome')

        await chat.waitForCompletion()
    }, 90_000)
})
