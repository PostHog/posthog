import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'

import { getPromptsFromManifest } from '@/resources'

export async function registerPrompts(server: McpServer): Promise<void> {
    // Get prompts from the manifest (they already have URIs substituted)
    const manifestPrompts = await getPromptsFromManifest()

    for (const prompt of manifestPrompts) {
        // Register as zero-argument prompt
        // The agent can discover available frameworks from the resource templates
        server.registerPrompt(
            prompt.name,
            {
                title: prompt.title,
                description: prompt.description,
            },
            async () => ({
                messages: prompt.messages as any,
            })
        )
    }
}
