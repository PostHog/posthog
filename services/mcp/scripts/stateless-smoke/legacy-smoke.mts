// Smoke-tests the PostHog MCP server's legacy dialect (≤2025-11-25) — the
// `initialize`-handshake protocol that every stable client (Claude, Cursor,
// VS Code, ChatGPT) speaks today — using the stable v1 SDK
// (@modelcontextprotocol/sdk, resolved from services/mcp/node_modules).
// The server implements this dialect statelessly, so beyond the SDK round
// trip this also proves requests survive without session affinity and that
// legacy results keep their exact pre-stateless wire shape (no `resultType`,
// no `_meta` server identity leaking across dialects).
//
// Usage: POSTHOG_PERSONAL_API_KEY=phx_... MCP_URL=http://localhost:8787/mcp \
//        ../../node_modules/.bin/tsx legacy-smoke.mts
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import { LATEST_PROTOCOL_VERSION } from '@modelcontextprotocol/sdk/types.js'

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

interface RpcEnvelope {
    result?: Record<string, unknown> & { _meta?: Record<string, unknown> }
    error?: { code?: number; message?: string }
}

async function rawPost(
    method: string,
    params: Record<string, unknown>
): Promise<{ response: Response; json: RpcEnvelope }> {
    const response = await fetch(MCP_URL, {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${TOKEN}`,
            'Content-Type': 'application/json',
            Accept: 'application/json, text/event-stream',
            'x-posthog-mcp-mode': 'tools',
        },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
    })
    return { response, json: (await response.json()) as RpcEnvelope }
}

// 1) Stable-SDK handshake: `initialize` negotiates a legacy version.
const transport = new StreamableHTTPClientTransport(new URL(MCP_URL), {
    requestInit: { headers: { Authorization: `Bearer ${TOKEN}`, 'x-posthog-mcp-mode': 'tools' } },
})
const client = new Client({ name: 'posthog-legacy-smoke', version: '0.0.1' }, { capabilities: {} })
await client.connect(transport)
check(
    'initialize negotiates a legacy version',
    transport.protocolVersion !== undefined && transport.protocolVersion !== STATELESS_VERSION,
    `negotiated=${transport.protocolVersion}`
)
check(
    'server identity from initialize',
    client.getServerVersion()?.name !== undefined,
    JSON.stringify(client.getServerVersion())
)

// 2) tools/list + a real tool call over the legacy dialect.
const tools = await client.listTools()
check('tools/list returns tools', tools.tools.length > 0, `${tools.tools.length} tools`)
const orgTool = tools.tools.find((t) => t.name === 'organization-get') ?? tools.tools[0]!
const result = await client.callTool({ name: orgTool.name, arguments: {} })
check(
    `tools/call ${orgTool.name}`,
    !result.isError,
    ((result.content as Array<{ text?: string }> | undefined)?.[0]?.text ?? '').slice(0, 80)
)
await client.close()

// 3) Wire-shape guard: legacy results must keep the pre-stateless shape —
//    the 2026-07-28 decoration (`resultType`, `_meta` server identity) must
//    not leak into a request that carries no `_meta` protocol version.
const legacyList = await rawPost('tools/list', {})
check(
    'legacy result carries no stateless decoration',
    legacyList.json.result !== undefined &&
        !('resultType' in legacyList.json.result) &&
        legacyList.json.result._meta?.[META_SERVER_INFO] === undefined
)

// 4) Fallback negotiation: an unknown requested version is answered with the
//    newest legacy version, not an error (spec fallback behavior).
const fallback = await rawPost('initialize', {
    protocolVersion: '1999-01-01',
    capabilities: {},
    clientInfo: { name: 'posthog-legacy-smoke', version: '0.0.1' },
})
check(
    'unknown initialize version falls back to newest legacy version',
    fallback.json.result?.protocolVersion === LATEST_PROTOCOL_VERSION,
    `answered=${String(fallback.json.result?.protocolVersion)}`
)

// 5) Stateless serving of the legacy dialect: a request on a fresh connection
//    with no prior initialize and no session id must still be served.
const bare = await rawPost('tools/list', {})
check(
    'legacy request without handshake or session id is served',
    bare.response.status === 200 && bare.json.error === undefined && Array.isArray(bare.json.result?.tools)
)

console.info(failures === 0 ? '\nAll checks passed' : `\n${failures} check(s) failed`)
process.exit(failures === 0 ? 0 : 1)
