import { z } from 'zod'

import { Prompts } from '@posthog/ai'

import { env } from '@/lib/env'
import type { FlagValue } from '@/lib/posthog/flags'

export const MCP_INTENT_PROMPT_FLAG = 'mcp-intent-prompt'
export const MCP_INTENT_PROMPT_NAME = 'mcp-tool-call-intent'

const intentPromptSchema = z.object({
    prompt_name: z.literal(MCP_INTENT_PROMPT_NAME),
    prompt_version: z.number().int().positive(),
})

export type IntentPrompt = z.infer<typeof intentPromptSchema>

let prompts: Prompts | undefined

export function resolveIntentPrompt(value: FlagValue, payload: unknown): IntentPrompt | undefined {
    if (value !== true && (typeof value !== 'string' || !value)) {
        return undefined
    }
    const result = intentPromptSchema.safeParse(payload)
    return result.success ? result.data : undefined
}

export async function loadIntentPrompt(reference?: IntentPrompt): Promise<string | undefined> {
    if (
        !reference ||
        !env.POSTHOG_PROMPTS_PERSONAL_API_KEY ||
        !env.POSTHOG_ANALYTICS_API_KEY ||
        !env.POSTHOG_PROMPTS_HOST
    ) {
        return undefined
    }
    try {
        prompts ??= new Prompts({
            personalApiKey: env.POSTHOG_PROMPTS_PERSONAL_API_KEY,
            projectApiKey: env.POSTHOG_ANALYTICS_API_KEY,
            host: env.POSTHOG_PROMPTS_HOST,
        })
        const result = await prompts.get(reference.prompt_name, { version: reference.prompt_version })
        if (result.name !== reference.prompt_name || result.version !== reference.prompt_version) {
            return undefined
        }
        const text = z.string().trim().min(1).max(2000).safeParse(result.prompt)
        return text.success ? text.data : undefined
    } catch {
        return undefined
    }
}
