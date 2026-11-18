import { z } from 'zod'

import type { FlagValue } from '@/lib/posthog/flags'

export const MCP_INTENT_PROMPT_FLAG = 'mcp-intent-prompt'

const intentPromptSchema = z.object({
    prompt: z.string().trim().min(1).max(2000),
})

export function resolveIntentPrompt(value: FlagValue, payload: unknown): string | undefined {
    if (value !== true && (typeof value !== 'string' || !value)) {
        return undefined
    }
    const result = intentPromptSchema.safeParse(payload)
    return result.success ? result.data.prompt : undefined
}
