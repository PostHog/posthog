import type { ListToolsResult } from '@modelcontextprotocol/sdk/types.js'
import { createHash } from 'node:crypto'
import { z } from 'zod'

import type { FlagValue } from '@/lib/posthog/flags'

export const MCP_INTENT_PROMPT_FLAG = 'mcp-intent-prompt'

const intentPromptSchema = z.object({
    prompt: z.string().trim().min(1).max(2000),
})

export interface IntentPromptExposure {
    intent_prompt_status: 'default' | 'trial' | 'injection_failed' | 'not_injected' | 'unknown'
    intent_prompt_text?: string
    intent_prompt_hash?: string
    intent_prompt_tools?: string[]
}

const servedContextSchema = z.object({ type: z.literal('string'), description: z.string().min(1) })

export function getIntentPromptExposure(
    originalTools: ListToolsResult['tools'],
    servedTools: ListToolsResult['tools'],
    trialPrompt?: string
): IntentPromptExposure {
    const originalByName = new Map(originalTools.map((tool) => [tool.name, tool]))
    const prompts = new Set<string>()
    const toolNames: string[] = []

    for (const tool of servedTools) {
        const original = originalByName.get(tool.name)
        // An application-owned context field is not an analytics prompt exposure.
        if (!original || Object.prototype.hasOwnProperty.call(original.inputSchema.properties ?? {}, 'context')) {
            continue
        }
        const context = servedContextSchema.safeParse(tool.inputSchema.properties?.context)
        if (context.success) {
            prompts.add(context.data.description)
            toolNames.push(tool.name)
        }
    }

    if (prompts.size === 0) {
        return { intent_prompt_status: 'not_injected' }
    }
    if (prompts.size !== 1) {
        return { intent_prompt_status: 'unknown' }
    }
    const prompt = Array.from(prompts)[0]!
    return {
        intent_prompt_status: trialPrompt ? (prompt === trialPrompt ? 'trial' : 'unknown') : 'default',
        intent_prompt_text: prompt,
        intent_prompt_hash: createHash('sha256').update(prompt).digest('hex'),
        intent_prompt_tools: toolNames,
    }
}

export function resolveIntentPrompt(value: FlagValue, payload: unknown): string | undefined {
    if (value !== true && (typeof value !== 'string' || !value)) {
        return undefined
    }
    const result = intentPromptSchema.safeParse(payload)
    return result.success ? result.data.prompt : undefined
}
