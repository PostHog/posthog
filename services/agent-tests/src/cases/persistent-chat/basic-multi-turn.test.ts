/**
 * Case 1: basic multi-turn over `/send`.
 *
 * Pins the simplest version of "chat works": start a session, observe
 * the first assistant turn, send a follow-up, observe a second turn
 * that incorporates the follow-up. The whole conversation history must
 * live in the queue row's persisted `state.messages`, NOT in the
 * runner's in-process Promise.
 *
 * Drives the REAL `AssServerExecutor` + Claude Agent SDK against the
 * harness's MockAnthropicServer. The fixture's `model: 'mock-echo'`
 * routes the SDK to the mock's built-in echo handler — each turn it
 * receives the user's text back as the assistant message. No stub
 * executors, no `__TEST_EXECUTOR`; if it works here, it works on the
 * production path.
 */
import { resolve } from 'node:path'

import { bundleAndUpload } from '../../harness/bundle'
import { post, send, waitForAwaitingInput } from '../../harness/clients'
import { type AgentCluster, getMockAnthropic, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-chat-basic-team-secret'
const FIXTURE_DIR = resolve(__dirname, '../../../fixtures/mock-echo')

describe('persistent-chat: basic multi-turn over /send', () => {
    let cluster: AgentCluster
    let bundleS3Key: string
    let bundleSha256: string

    beforeAll(async () => {
        cluster = await openSharedCluster()
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

    it('two-turn conversation: state.messages grows by turn; both user inputs visible in DB', async () => {
        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'chat-basic-two-turn',
            auth: { type: 'pat' },
            bundle: { s3Key: bundleS3Key, sha256: bundleSha256 },
        })

        // Turn 1: kick off the session with an initial body.
        const run = await post(cluster, app.slug, { pat: TEAM_SECRET, body: { message: 'hello' } })
        expect(run.status).toBe(202)
        const sessionId = run.body.sessionId as string

        // The SDK turn ends after one assistant message; the worker
        // parks the job at status=available, turnCount=1.
        const afterTurn1 = await waitForAwaitingInput(cluster, sessionId, { afterTurn: 1, timeoutMs: 30_000 })
        expect(afterTurn1.state?.messages.map((m) => m.role)).toEqual(['user', 'assistant'])
        expect(afterTurn1.state?.messages[0].content).toBe('hello')
        expect(afterTurn1.state?.messages[1].content).toBe('hello')
        expect(afterTurn1.state?.turnCount).toBe(1)

        // Turn 2: follow-up. `/send` writes to pending_inputs durably
        // AND advances `scheduled` to NOW so the worker picks the job
        // up immediately.
        const followup = await send(cluster, app.slug, sessionId, 'and another thing', { pat: TEAM_SECRET })
        expect(followup.status).toBe(202)

        const afterTurn2 = await waitForAwaitingInput(cluster, sessionId, { afterTurn: 2, timeoutMs: 30_000 })
        expect(afterTurn2.state?.messages.map((m) => m.role)).toEqual([
            'user',
            'assistant', // turn 1
            'user',
            'assistant', // turn 2
        ])
        expect(afterTurn2.state?.messages[2].content).toBe('and another thing')
        expect(afterTurn2.state?.messages[3].content).toBe('and another thing')
        expect(afterTurn2.pendingInputsColumn).toHaveLength(0)
        expect(afterTurn2.state?.turnCount).toBe(2)
    }, 60_000)
})
