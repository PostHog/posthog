/**
 * App test: SecretBroker nonce substitution at egress.
 *
 * The security-critical path under test: a custom tool's `inputs:`
 * declares `WEBHOOK_URL` as a secret. At call time, `ctx.secrets.ref(...)`
 * hands the tool a `{{secret:<hex>}}` nonce, never the URL. The nonce
 * goes into `ctx.http.fetch`'s URL arg, lands in the egress proxy inside
 * the sandbox container, and only at that final hop is it swapped for
 * the real URL. The container's logs, the model's transcript, and our
 * log_entries should NEVER see the real URL.
 *
 * The webhook tester (running as part of the hogli stack on :2080)
 * captures inbound requests so we can prove the substitution actually
 * happened — the request arrived at the real URL.
 *
 * Requires: AGENT_E2E_REAL_LLM=1 + ANTHROPIC_API_KEY + Docker +
 * webhook-tester at :2080 (override via WEBHOOK_TESTER_URL).
 */
import { resolve } from 'node:path'

import { bundleAndUpload } from '../../harness/bundle'
import { chatFlow } from '../../harness/chat'
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'
import { REAL_LLM, describeRealLlm } from '../../harness/llm'

const FIXTURE_DIR = resolve(__dirname, '../../../fixtures/wired')
const TEAM_SECRET = 'e2e-app-wired-team-secret'
// The URL the webhook actually targets. The substitution happens in the
// worker-side egress proxy (NOT inside the sandbox container), so the
// real fetch is made from the host process — localhost is the right
// hop, not host.docker.internal.
const TESTER_URL = process.env.WEBHOOK_TESTER_URL ?? 'http://localhost:2080'

interface TesterSession {
    uuid: string
    /** URL the agent should POST to. Reachable from inside the sandbox container. */
    deliveryUrl: string
    /** URL the test harness uses to read back captured requests. */
    inspectUrl: string
}

async function createTesterSession(): Promise<TesterSession> {
    // Host-side URL (works inside Docker via host.docker.internal); the
    // tester API itself is local to the test process.
    const apiBase = process.env.WEBHOOK_TESTER_API_URL ?? TESTER_URL
    const res = await fetch(`${apiBase}/api/session`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
            status_code: 200,
            content_type: 'application/json',
            response_delay: 0,
            response_body_base64: 'e30=',
        }),
    })
    if (!res.ok) {
        throw new Error(`webhook-tester not reachable at ${apiBase} (status ${res.status})`)
    }
    const { uuid } = (await res.json()) as { uuid: string }
    return {
        uuid,
        deliveryUrl: `${TESTER_URL}/${uuid}`,
        inspectUrl: `${apiBase}/api/session/${uuid}/requests`,
    }
}

interface CapturedRequest {
    request_payload_base64: string
}

async function readCaptured(session: TesterSession): Promise<CapturedRequest[]> {
    const res = await fetch(session.inspectUrl)
    if (!res.ok) {
        throw new Error(`webhook-tester inspect failed (status ${res.status})`)
    }
    return (await res.json()) as CapturedRequest[]
}

describeRealLlm('app: SecretBroker substitutes a nonce at egress and never leaks the URL', () => {
    let cluster: AgentCluster
    let bundleS3Key: string
    let bundleSha256: string

    beforeAll(async () => {
        if (!REAL_LLM) {
            return
        }
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
        const uploaded = await bundleAndUpload(cluster.cleanup, FIXTURE_DIR)
        const wired = uploaded.find((b) => b.agentSlug === 'e2e-wired')
        if (!wired) {
            throw new Error('bundleAndUpload returned no e2e-wired')
        }
        bundleS3Key = wired.bundleS3Key
        bundleSha256 = wired.bundleSha256
    }, 120_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 60_000)

    it('calls the webhook via a substituted nonce; webhook-tester records the request, log_entries never see the URL', async () => {
        const session = await createTesterSession()

        const app = await createApp(cluster.cleanup, {
            slugSuffix: 'app-wired',
            auth: { type: 'pat' },
            bundle: { s3Key: bundleS3Key, sha256: bundleSha256 },
            encryptedEnv: { WEBHOOK_URL: session.deliveryUrl },
        })

        // Sanity: read back the env through the same repository the
        // runner uses. A miss here would mean the secret never persisted
        // (or the dotenv encoding is wrong) — an ambiguous test failure
        // becomes a clear one.
        const decrypted = await cluster.repository.decryptEnv(app.applicationId)
        expect(decrypted).toEqual({ WEBHOOK_URL: session.deliveryUrl })

        const chat = chatFlow(cluster, app.slug, {
            pat: TEAM_SECRET,
            firstMessage: 'fire the webhook',
            waitTimeoutMs: 120_000,
        })

        const reply = await chat.waitForReply()
        // The agent reports the status the tool returned. 200 means
        // substitution succeeded (the request reached the tester);
        // a missing/leaked nonce would show as the tester not seeing it.
        expect(reply.text).toContain('200')

        await chat.waitForCompletion()
        const sessionId = await chat.sessionId

        // The tester captured the request — proves the substitution.
        const captured = await readCaptured(session)
        expect(captured.length).toBeGreaterThan(0)
        const decoded = Buffer.from(captured[0].request_payload_base64, 'base64').toString('utf8')
        expect(decoded).toContain('"title":"ping"')
        expect(decoded).toContain('"body":"e2e"')

        // Security claim: the URL never lands in any log entry. The
        // tool's CODE only ever held a nonce (`ctx.secrets.ref(...)`); the
        // model never saw the URL at all (it's not in the tool's args
        // schema); and the bridge/session_logger redact nothing — the URL
        // simply has no surface area to leak from. The check below catches
        // a regression where (e.g.) someone logs the secrets dict into
        // session metadata, or the egress substitution runs in the wrong
        // process and ends up logged by the runner.
        const rows = await cluster.clickhouse.logsForSession(sessionId)
        const toolCallLines = rows.filter((r) => r.message.startsWith('[tool] '))
        expect(toolCallLines.some((r) => r.message.includes('hook__deliver'))).toBe(true)
        for (const row of rows) {
            expect(row.message).not.toContain(session.deliveryUrl)
            expect(row.message).not.toContain(session.uuid)
        }
    }, 180_000)
})
