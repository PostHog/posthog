/**
 * PiClient — the runner's LLM-invocation surface. Backed by `@earendil-works/pi-ai`,
 * the unified TS SDK that handles Anthropic / OpenAI / Bedrock / Google / Mistral
 * / any OpenAI-compatible endpoint (which includes PostHog's llm-gateway).
 *
 * The runner never knows which provider it actually hit — model selection
 * happens here, in `resolveModel()`, based on `spec.model` from the revision.
 *
 * Test paths register the faux provider and supply a `faux/<id>` model spec.
 * Real-inference paths use the real provider id (`anthropic/claude-sonnet-4-7`,
 * `openai/gpt-4o-mini`, etc.) — same code path, different model.
 */

import {
    AssistantMessage,
    complete,
    Context,
    getModel,
    KnownProvider,
    Model,
    ProviderStreamOptions,
} from '@earendil-works/pi-ai'

export interface PiClient {
    /**
     * Run one assistant turn against the given context. Returns the raw
     * AssistantMessage from pi-ai — the runner pushes it into the conversation
     * and inspects `content[]` for `toolCall` blocks.
     */
    invoke(context: Context, opts?: InvokeOpts): Promise<AssistantMessage>
}

export interface InvokeOpts {
    maxTokens?: number
    temperature?: number
    /** Cancel the in-flight request (used for shutdown). */
    signal?: AbortSignal
}

/** Production impl. Backed by pi-ai's `complete()`. */
export class PiAiClient implements PiClient {
    constructor(
        private readonly model: Model<string>,
        private readonly apiKey?: string
    ) {}

    async invoke(context: Context, opts?: InvokeOpts): Promise<AssistantMessage> {
        const streamOpts: ProviderStreamOptions = {
            apiKey: this.apiKey,
            maxTokens: opts?.maxTokens,
            temperature: opts?.temperature,
            signal: opts?.signal,
        }
        return complete(this.model, context, streamOpts)
    }
}

/**
 * Resolve a spec.model string to a pi-ai `Model`. Format:
 *   "<provider>/<model-id>"           — built-in pi-ai providers
 *   "faux/<model-id>"                 — scripted faux model (tests register first)
 *
 * For custom endpoints (llm-gateway, Ollama, etc.) callers build the Model
 * directly and skip this helper — see `llm-gateway-model.ts`.
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
