// Smoke-tests the PostHog MCP server's 2026-07-28 stateless dialect using the
// official beta client SDK (@modelcontextprotocol/client v2). The version is
// pinned so the SDK refuses to fall back to the legacy `initialize` handshake:
// every request must carry `_meta` protocol identity and succeed statelessly.
//
// Usage: POSTHOG_PERSONAL_API_KEY=phx_... MCP_URL=http://localhost:8787/mcp \
//        ../../node_modules/.bin/tsx stateless-smoke.mts
import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client'

const MCP_URL = process.env.MCP_URL ?? 'http://localhost:8787/mcp'
const TOKEN = process.env.POSTHOG_PERSONAL_API_KEY
const STATELESS_VERSION = '2026-07-28'
const META_SERVER_INFO = 'io.modelcontextprotocol/serverInfo'

if (!TOKEN) {
    console.error('POSTHOG_PERSONAL_API_KEY is required')
    process.exit(1)
}

let failures = 0

function check(name: string, ok: boolean, detail?: string): void {
    failures += ok ? 0 : 1
    console.info(`${ok ? '✅' : '❌'} ${name}${detail ? ` — ${detail}` : ''}`)
}

function makeTransport(): StreamableHTTPClientTransport {
    return new StreamableHTTPClientTransport(new URL(MCP_URL), {
        authProvider: { token: async () => TOKEN! },
        requestInit: { headers: { 'x-posthog-mcp-mode': 'tools' } },
    })
}

// 1) Pinned stateless connect: the SDK must reach the modern era via
//    `server/discover` — no `initialize`, no session id.
const client = new Client(
    { name: 'posthog-stateless-smoke', version: '0.0.1' },
    { versionNegotiation: { mode: { pin: STATELESS_VERSION } } }
)
await client.connect(makeTransport())
check(
    'connect pinned to 2026-07-28',
    client.getNegotiatedProtocolVersion() === STATELESS_VERSION,
    `negotiated=${client.getNegotiatedProtocolVersion()}`
)

// 2) server/discover: capability discovery without a handshake.
const discovered = await client.discover()
check('server/discover returns capabilities', !!discovered.capabilities?.tools)
check(
    'server identity in result _meta',
    (discovered._meta?.[META_SERVER_INFO] as { name?: string } | undefined)?.name !== undefined,
    JSON.stringify(discovered._meta?.[META_SERVER_INFO])
)

// 3) tools/list over the stateless dialect.
const tools = await client.listTools()
check('tools/list returns tools', tools.tools.length > 0, `${tools.tools.length} tools`)

// 4) A real tool call round-trip.
const orgTool = tools.tools.find((t) => t.name === 'organization-get') ?? tools.tools[0]!
const result = await client.callTool({ name: orgTool.name, arguments: {} })
check(
    `tools/call ${orgTool.name}`,
    !result.isError,
    (result.content?.[0] as { text?: string } | undefined)?.text?.slice(0, 120)
)
await client.close()

// 5) Statelessness proper: a second, fresh connection (new transport, no
//    carried session) must serve a tool call just as well.
const client2 = new Client(
    { name: 'posthog-stateless-smoke-2', version: '0.0.1' },
    { versionNegotiation: { mode: { pin: STATELESS_VERSION } } }
)
await client2.connect(makeTransport())
const result2 = await client2.callTool({ name: orgTool.name, arguments: {} })
check('fresh connection serves tools/call (no session affinity)', !result2.isError)
await client2.close()

// 6) Wire-level negative check the SDK can't express: a legacy version inside
//    `_meta` must be rejected with UnsupportedProtocolVersionError (-32022).
const rawResponse = await fetch(MCP_URL, {
    method: 'POST',
    headers: {
        Authorization: `Bearer ${TOKEN}`,
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
    },
    body: JSON.stringify({
        jsonrpc: '2.0',
        id: 99,
        method: 'tools/list',
        params: { _meta: { 'io.modelcontextprotocol/protocolVersion': '2025-11-25' } },
    }),
})
const rawJson = (await rawResponse.json()) as {
    error?: { code?: number; data?: { supported?: string[] } }
}
check(
    'legacy version in _meta rejected with -32022',
    rawJson.error?.code === -32022 && rawJson.error.data?.supported?.includes(STATELESS_VERSION) === true,
    JSON.stringify(rawJson.error)
)

console.info(failures === 0 ? '\nAll checks passed' : `\n${failures} check(s) failed`)
process.exit(failures === 0 ? 0 : 1)
