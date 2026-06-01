/**
 * Custom pi-ai `Model` pointed at PostHog's ai-gateway (the external
 * Go service that fronts every provider and owns usage / billing —
 * see github.com/PostHog/ai-gateway).
 *
 * ai-gateway speaks OpenAI-compatible chat completions on
 * `POST /v1/chat/completions`, so we use pi-ai's `openai-completions`
 * api spec with a custom `baseUrl`. Auth: a PostHog ai-gateway PAT
 * (`phx_...`) passed as the bearer token.
 *
 * Usage:
 *   const model = posthogAiGatewayModel({ modelId: 'gpt-4.1-mini', baseUrl: cfg.aiGatewayUrl })
 *   // pass `model` to the Worker via resolveModel + the gateway PAT via resolveApiKey
 *
 * The `baseUrl` default matches the in-cluster service name; dev / prod
 * override it through the runner's `AgentRunnerConfig`.
 */

import type { Model } from '@earendil-works/pi-ai'

export interface AiGatewayModelOpts {
    modelId: string
    /** Defaults to `http://ai-gateway/v1` — set in prod / dev to the appropriate URL via runner config. */
    baseUrl?: string
    /** Display name shown in logs. */
    displayName?: string
    contextWindow?: number
    maxTokens?: number
}

/**
 * Map a spec.model string (e.g. `openai/gpt-4o`) to the provider-native SKU
 * the ai-gateway's admission layer accepts. The gateway's `CanonicalForSKU`
 * lookup is keyed on bare ids (`gpt-4o`, `claude-sonnet-4-5`), not on the
 * canonical `<provider>/<model>` form. Strip the prefix; callers that need
 * a different mapping (anthropic version-name skew, etc.) can override here.
 */
export function aiGatewaySkuFor(specModel: string): string {
    const slash = specModel.indexOf('/')
    return slash === -1 ? specModel : specModel.slice(slash + 1)
}

export function posthogAiGatewayModel(opts: AiGatewayModelOpts): Model<'openai-completions'> {
    return {
        id: opts.modelId,
        name: opts.displayName ?? `${opts.modelId} (PostHog ai-gateway)`,
        api: 'openai-completions',
        provider: 'posthog-ai-gateway',
        baseUrl: opts.baseUrl ?? 'http://ai-gateway/v1',
        reasoning: false,
        input: ['text'],
        // Gateway tracks usage server-side; client-side cost is purely informational.
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: opts.contextWindow ?? 200_000,
        maxTokens: opts.maxTokens ?? 16_384,
    }
}
