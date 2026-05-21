import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import {
    GetPromptRequestSchema,
    ListPromptsRequestSchema,
    type GetPromptResult,
    type ListPromptsResult,
    type Prompt,
} from '@modelcontextprotocol/sdk/types.js'

import { getPromptsFromManifest } from '@/resources'

// Install `prompts/list` and `prompts/get` handlers directly on the underlying
// Server, bypassing `McpServer.registerPrompt`. The SDK only auto-registers
// these handlers on the first `registerPrompt` call — so when the manifest is
// empty, the Cloudflare Workers runtime answers `prompts/list` with "Method
// not found". The Hono dispatcher always answers (with `{ prompts: [] }`).
// Mirror that here so the two transports agree on the protocol surface.
export async function registerPrompts(server: McpServer): Promise<void> {
    const manifestPrompts = await getPromptsFromManifest()

    const prompts: Prompt[] = manifestPrompts.map((p) => ({
        name: p.name,
        title: p.title,
        description: p.description,
    }))
    const promptsByName = new Map<string, GetPromptResult>(
        manifestPrompts.map((p) => [p.name, { messages: p.messages as GetPromptResult['messages'] }])
    )

    server.server.registerCapabilities({ prompts: { listChanged: false } })

    server.server.setRequestHandler(ListPromptsRequestSchema, (): ListPromptsResult => ({ prompts }))
    server.server.setRequestHandler(GetPromptRequestSchema, (request): GetPromptResult => {
        const name = request.params?.name ?? ''
        return promptsByName.get(name) ?? { messages: [] }
    })
}
