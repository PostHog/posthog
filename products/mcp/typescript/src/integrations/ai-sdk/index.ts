import { ApiClient } from '@/api/client'
import { SessionManager } from '@/lib/utils/SessionManager'
import { StateManager } from '@/lib/utils/StateManager'
import { MemoryCache } from '@/lib/utils/cache/MemoryCache'
import { hash } from '@/lib/utils/helper-functions'
import { getToolsFromContext } from '@/tools'
import type { Context } from '@/tools/types'
import { type Tool as VercelTool, tool } from 'ai'
import type { z } from 'zod'

/**
 * Options for the PostHog Agent Toolkit
 */
export type PostHogToolsOptions = {
    posthogPersonalApiKey: string
    posthogApiBaseUrl: string
}

export class PostHogAgentToolkit {
    public options: PostHogToolsOptions

    /**
     * Create a new PostHog Agent Toolkit
     * @param options - The options for the PostHog Agent Toolkit
     */
    constructor(options: PostHogToolsOptions) {
        this.options = options
    }

    /**
     * Get the context for the PostHog Agent Toolkit
     * @returns A context object
     */
    getContext(): Context {
        const api = new ApiClient({
            apiToken: this.options.posthogPersonalApiKey,
            baseUrl: this.options.posthogApiBaseUrl,
        })

        const scope = hash(this.options.posthogPersonalApiKey)
        const cache = new MemoryCache(scope)

        return {
            api,
            cache,
            env: {
                INKEEP_API_KEY: undefined,
            },
            stateManager: new StateManager(cache, api),
            sessionManager: new SessionManager(cache),
        }
    }

    /**
     * Get all the tools for the PostHog Agent Toolkit
     * @returns A record of tool names to Vercel tools
     */
    async getTools(): Promise<Record<string, VercelTool>> {
        const context = this.getContext()
        const allTools = await getToolsFromContext(context)

        return allTools.reduce(
            (acc, t) => {
                acc[t.name] = tool({
                    description: t.description,
                    inputSchema: t.schema,
                    execute: async (arg: z.output<typeof t.schema>) => {
                        return t.handler(context, arg)
                    },
                })

                return acc
            },
            {} as Record<string, VercelTool>
        )
    }
}
