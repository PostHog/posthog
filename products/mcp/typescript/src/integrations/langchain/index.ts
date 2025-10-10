import { ApiClient } from '@/api/client'
import { SessionManager } from '@/lib/utils/SessionManager'
import { StateManager } from '@/lib/utils/StateManager'
import { MemoryCache } from '@/lib/utils/cache/MemoryCache'
import { hash } from '@/lib/utils/helper-functions'
import { getToolsFromContext } from '@/tools'
import type { Context } from '@/tools/types'
import { DynamicStructuredTool } from '@langchain/core/tools'
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
     * @returns An array of DynamicStructuredTool tools
     */
    async getTools(): Promise<DynamicStructuredTool[]> {
        const context = this.getContext()
        const allTools = await getToolsFromContext(context)

        return allTools.map((t) => {
            return new DynamicStructuredTool({
                name: t.name,
                description: t.description,
                schema: t.schema,
                func: async (arg: z.output<typeof t.schema>) => {
                    const result = await t.handler(context, arg)

                    if (typeof result === 'string') {
                        return result
                    }

                    const text = result.content.map((c: { text: string }) => c.text).join('\n')

                    return text
                },
            })
        })
    }
}
