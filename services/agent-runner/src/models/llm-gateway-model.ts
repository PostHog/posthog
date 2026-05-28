/**
 * Custom pi-ai `Model` pointed at PostHog's services/llm-gateway.
 *
 * llm-gateway speaks OpenAI-compatible chat completions on `POST /v1/chat/completions`,
 * so we use pi-ai's `openai-completions` api spec with a custom `baseUrl`.
 * Auth: a PostHog gateway PAT (`phx_...`) passed as the bearer token.
 *
 * Usage:
 *   const model = posthogLlmGatewayModel({ modelId: 'gpt-4.1-mini' })
 *   const client = new PiAiClient(model, process.env.POSTHOG_LLM_GATEWAY_KEY)
 */

import type { Model } from '@earendil-works/pi-ai'

export interface LlmGatewayModelOpts {
    modelId: string
    /** Defaults to `http://llm-gateway/v1` — set in prod to the in-cluster URL. */
    baseUrl?: string
    /** Display name shown in logs. */
    displayName?: string
    contextWindow?: number
    maxTokens?: number
}

export function posthogLlmGatewayModel(opts: LlmGatewayModelOpts): Model<'openai-completions'> {
    return {
        id: opts.modelId,
        name: opts.displayName ?? `${opts.modelId} (PostHog llm-gateway)`,
        api: 'openai-completions',
        provider: 'posthog-llm-gateway',
        baseUrl: opts.baseUrl ?? process.env.POSTHOG_LLM_GATEWAY_URL ?? 'http://llm-gateway/v1',
        reasoning: false,
        input: ['text'],
        // Gateway tracks usage server-side; client-side cost is purely informational.
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: opts.contextWindow ?? 200_000,
        maxTokens: opts.maxTokens ?? 16_384,
    }
}
