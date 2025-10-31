import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { z } from 'zod'

import type { Context } from '@/tools/types'
import { setupEventsPrompt } from './setup-events'

export interface Prompt {
    name: string
    title: string
    description: string
    argsSchema?: Record<string, z.ZodType<any>>
    handler: (
        context: Context,
        args: any
    ) => Promise<{
        messages: Array<{
            role: 'user' | 'assistant'
            content: {
                type: 'text'
                text: string
            }
        }>
    }>
}

export async function getPromptsFromContext(context: Context): Promise<Prompt[]> {
    return [await setupEventsPrompt(context)]
}

export async function registerPrompts(server: McpServer, context: Context) {
    const prompts = await getPromptsFromContext(context)

    for (const prompt of prompts) {
        if (prompt.argsSchema) {
            server.registerPrompt(
                prompt.name,
                {
                    description: prompt.description,
                    argsSchema: prompt.argsSchema,
                },
                async (args) => prompt.handler(context, args)
            )
        } else {
            server.registerPrompt(
                prompt.name,
                {
                    description: prompt.description,
                },
                async () => prompt.handler(context, {})
            )
        }
    }
}
