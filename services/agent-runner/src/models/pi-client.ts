/**
 * PiClient — the runner's LLM-invocation surface. Backed by `@earendil-works/pi-ai`,
 * the unified TS SDK that handles Anthropic / OpenAI / Bedrock / Google / Mistral
 * / any OpenAI-compatible endpoint (which includes PostHog's llm-gateway).
 *
 * Per-call model: each `invoke()` takes the Model to use. The runner resolves
 * `rev.spec.model` to a Model object per session, so different agents on the
 * same worker process can target different providers/models.
 */

import {
    AssistantMessage,
    completeSimple,
    Context,
    getModel,
    KnownProvider,
    Model,
    SimpleStreamOptions,
} from '@earendil-works/pi-ai'

import type { ReasoningEffort } from '@posthog/agent-shared'

export interface PiClient {
    /**
     * Run one assistant turn with the given model + context. Returns the raw
     * AssistantMessage from pi-ai — the runner pushes it into the conversation
     * and inspects `content[]` for `toolCall` blocks.
     */
    invoke(model: Model<string>, context: Context, opts?: InvokeOpts): Promise<AssistantMessage>
}

export interface InvokeOpts {
    maxTokens?: number
    temperature?: number
    /** Override the apiKey used for this call (defaults to the client's default). */
    apiKey?: string
    /** Cancel the in-flight request (used for shutdown). */
    signal?: AbortSignal
    /**
     * Reasoning-effort knob for reasoning-capable models (Anthropic extended
     * thinking, OpenAI o-series, Gemini thinking). Forwarded to pi-ai's
     * `completeSimple({ reasoning })`. Non-reasoning models ignore it.
     * Omit to use the provider default.
     */
    reasoning?: ReasoningEffort
}

/**
 * Production impl. Backed by pi-ai's `completeSimple()`. The default `apiKey`
 * is applied to every call unless `InvokeOpts.apiKey` overrides. Switched from
 * the bare `complete()` so the typed `reasoning` knob is available without
 * stuffing it into an open-record bag.
 */
export class PiAiClient implements PiClient {
    constructor(private readonly defaultApiKey?: string) {}

    async invoke(model: Model<string>, context: Context, opts?: InvokeOpts): Promise<AssistantMessage> {
        const streamOpts: SimpleStreamOptions = {
            apiKey: opts?.apiKey ?? this.defaultApiKey,
            maxTokens: opts?.maxTokens,
            temperature: opts?.temperature,
            signal: opts?.signal,
            reasoning: opts?.reasoning,
        }
        return completeSimple(model, context, streamOpts)
    }
}

/**
 * Resolve a `spec.model` string to a pi-ai `Model`. Format:
 *   "<provider>/<model-id>"           — built-in pi-ai providers
 *   "faux/<model-id>"                 — scripted faux model (tests register first)
 *
 * For custom endpoints (llm-gateway, Ollama, etc.) callers build the Model
 * directly via `posthogLlmGatewayModel()` and pass it in.
 */
export function resolveModel(specModel: string): Model<string> {
    const slash = specModel.indexOf('/')
    if (slash === -1) {
        throw new Error(`spec.model must be "<provider>/<model-id>" (got ${JSON.stringify(specModel)})`)
    }
    const provider = specModel.slice(0, slash)
    const modelId = specModel.slice(slash + 1)
    return getModel(provider as KnownProvider, modelId as never) as Model<string>
}

/**
 * Cache of resolved Models keyed by spec.model string. Avoids re-resolving the
 * same string in tight loops.
 */
const MODEL_CACHE = new Map<string, Model<string>>()

export function resolveModelCached(specModel: string): Model<string> {
    let m = MODEL_CACHE.get(specModel)
    if (!m) {
        m = resolveModel(specModel)
        MODEL_CACHE.set(specModel, m)
    }
    return m
}

/** Clear the resolver cache. Tests call this when re-registering faux models. */
export function clearModelCache(): void {
    MODEL_CACHE.clear()
}
