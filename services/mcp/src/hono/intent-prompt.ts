import { z } from 'zod'

import type { FlagValue } from '@/lib/posthog/flags'

export const MCP_INTENT_PROMPT_FLAG = 'mcp-intent-prompt'
export const MCP_INTENT_PROMPT_NAME = 'mcp-tool-call-intent'

const intentPromptSchema = z.object({
    prompt_name: z.literal(MCP_INTENT_PROMPT_NAME),
    prompt_version: z.number().int().positive(),
    prompt: z.string().trim().min(1).max(2000),
})

export type IntentPrompt = z.infer<typeof intentPromptSchema>

export function resolveIntentPrompt(value: FlagValue, payload: unknown): IntentPrompt | undefined {
    if (value !== true && (typeof value !== 'string' || !value)) {
        return undefined
    }
    const result = intentPromptSchema.safeParse(payload)
    return result.success ? result.data : undefined
}
