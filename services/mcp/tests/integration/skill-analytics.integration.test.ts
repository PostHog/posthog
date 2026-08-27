import http from 'node:http'
import { gunzipSync } from 'node:zlib'

import { afterAll, beforeAll, describe, expect, it } from 'vitest'

/**
 * End-to-end proof that a real skill read reaches PostHog carrying the skill's name.
 *
 * Only the destination is substituted: a local HTTP sink stands in for ingestion so
 * the outbound payload can be read. Everything upstream is real — the real
 * ToolExecutor, the real `exec` dispatcher, the real `skill-get` handler fetching a
 * real skill over HTTPS, and the real analytics client serializing the event.
 *
 *   POSTHOG_PERSONAL_API_KEY=... npx vitest run \
 *     tests/integration/skill-analytics.integration.test.ts \
 *     --config vitest.integration.config.mts
 *
 * Run by hand, not by CI. It reads `POSTHOG_PERSONAL_API_KEY` rather than the
 * `TEST_`-prefixed variables the CI integration job supplies, so it always skips
 * there. That is deliberate: it names one skill on one real instance, which is a
 * fact about that project rather than about this code, so asserting it in CI would
 * fail against the e2e stack and add a network dependency to a suite that has none.
 * The wiring itself is covered by the unit and hono suites, which do run in CI.
 */

const API_TOKEN = process.env.POSTHOG_PERSONAL_API_KEY
const API_HOST = process.env.POSTHOG_API_HOST ?? 'https://us.posthog.com'
const PROJECT_ID = process.env.POSTHOG_PROJECT_ID ?? '2'
// A skill that exists in the target project. Override when running elsewhere.
const SKILL = process.env.E2E_SKILL_NAME ?? 'conductor'

const captured: any[] = []
let sink: http.Server
let sinkPort: number

describe.skipIf(!API_TOKEN)('skill read reaches PostHog with $mcp_skill_name', () => {
    beforeAll(async () => {
        sink = http.createServer((req, res) => {
            const chunks: Buffer[] = []
            req.on('data', (c: Buffer) => chunks.push(c))
            req.on('end', () => {
                try {
                    const raw = Buffer.concat(chunks)
                    // posthog-node gzips the batch before POSTing it to /batch/.
                    const json = req.headers['content-encoding'] === 'gzip' ? gunzipSync(raw) : raw
                    const body = JSON.parse(json.toString())
                    for (const item of body.batch ?? [body]) {
                        captured.push(item)
                    }
                } catch {
                    // non-JSON probe; ignore
                }
                res.writeHead(200, { 'content-type': 'application/json' })
                res.end('{"status":1}')
            })
        })
        await new Promise<void>((resolve) => sink.listen(0, '127.0.0.1', resolve))
        sinkPort = (sink.address() as { port: number }).port

        // Set before the analytics client is imported — it is a module-level singleton.
        process.env.POSTHOG_ANALYTICS_API_KEY = 'phc_e2e_local_sink'
        process.env.POSTHOG_ANALYTICS_HOST = `http://127.0.0.1:${sinkPort}`
    })

    afterAll(async () => {
        await new Promise<void>((resolve) => sink?.close(() => resolve()))
    })

    it('fetches the real skill and emits an event naming it', async () => {
        const [{ ApiClient }, { ToolCatalog }, { ToolExecutor }, { InstructionsBuilder }, { getPostHogClient }] =
            await Promise.all([
                import('@/api/client'),
                import('@/hono/tool-catalog'),
                import('@/hono/tool-executor'),
                import('@/hono/instructions'),
                import('@/lib/posthog/client'),
            ])

        const api = new ApiClient({ apiToken: API_TOKEN!, baseUrl: API_HOST })
        const catalog = new ToolCatalog()
        await catalog.warmup()
        const executor = new ToolExecutor(catalog, new InstructionsBuilder(''))

        const tools = catalog.getPreBuiltEntries().map((entry) => {
            const preBuilt = catalog.getToolByName(entry.name)!
            return {
                ...preBuilt.base,
                title: entry.title,
                description: entry.description ?? '',
                annotations: entry.annotations,
                scopes: [],
            }
        })

        const state: any = {
            reqCtx: {
                cache: { get: async () => undefined, set: async () => undefined },
                safelyGetAnalyticsContext: async () => undefined,
                trackEvent: () => {},
                trackContextSwitchEvent: () => {},
                getSessionUuid: async () => 'e2e-session',
                getEffectiveSessionUuid: async () => 'e2e-session',
            },
            context: {
                api,
                cache: {},
                env: {},
                stateManager: { getProjectId: async () => PROJECT_ID },
                sessionManager: {},
                getDistinctId: () => 'e2e-distinct-id',
                trackEvent: () => {},
            },
            useSingleExec: true,
            toolFeatureFlags: undefined,
            apiKeyScopes: [],
            oauthClientId: undefined,
            clientProfile: {
                capabilities: { supportsInstructions: true },
                isCliModeEnabled: () => true,
                isClaudeUiHost: () => false,
                isInlineExecUiHost: () => false,
                isClaudeChatHost: () => false,
            },
            requestContext: {
                authMethod: 'personal_api_key',
                sessionId: 'e2e-session',
                mcpClientName: 'e2e-harness',
                mcpClientVersion: '1.0',
                mcpProtocolVersion: '2025-03-26',
                transport: 'streamable-http',
            },
            sessionContext: null,
            allTools: tools,
            scopeGatedTools: [],
            gatewayToolsEnabled: false,
            distinctId: 'e2e-distinct-id',
            renderUiEnabled: false,
        }

        // Exactly the shape an agent sends: single-exec mode, skill name inside the command.
        const command = `call skill-get {"skill_name":"${SKILL}","body_offset":0}`
        console.info(`\n→ MCP tools/call   exec   ${command}`)

        const result: any = await executor.handleToolCall({ name: 'exec', arguments: { command } }, state)
        const text: string = result?.content?.[0]?.text ?? ''

        console.info(`← ${API_HOST} returned ${text.length} chars, isError=${result?.isError ?? false}`)

        // `trackToolCall` is fired with `void` and awaits async context lookups, so the
        // capture lands after the handler returns. Let it settle before flushing.
        await new Promise((r) => setTimeout(r, 1500))
        await getPostHogClient().flush()
        await new Promise((r) => setTimeout(r, 1000))
        console.info(`  sink received ${captured.length} event(s): ${captured.map((e) => e.event).join(', ')}`)

        const toolCall = captured.find((e) => e.event === '$mcp_tool_call')
        const props = toolCall?.properties ?? {}

        console.info('\n── $mcp_tool_call as PostHog ingestion would receive it ──')
        console.info(
            JSON.stringify(
                Object.fromEntries(
                    Object.entries(props).filter(([k]) =>
                        [
                            '$mcp_skill_name',
                            '$mcp_skill_body_offset',
                            '$mcp_tool_name',
                            '$mcp_exec_verb',
                            '$mcp_exec_target_tool',
                            '$mcp_is_error',
                        ].includes(k)
                    )
                ),
                null,
                2
            )
        )
        console.info(`\n✓ $mcp_skill_name = ${JSON.stringify(props.$mcp_skill_name)}\n`)

        // The skill really came back from the API, not from a fixture or an error path.
        expect(result?.isError ?? false).toBe(false)
        expect(text.length).toBeGreaterThan(500)

        expect(toolCall).not.toBeUndefined()
        expect(props.$mcp_tool_name).toBe('skill-get')
        expect(props.$mcp_skill_name).toBe(SKILL)
        expect(props.$mcp_skill_body_offset).toBe(0)
    })
})
