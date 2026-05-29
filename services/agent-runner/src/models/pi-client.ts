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
    AssistantMessageEvent,
    completeSimple,
    Context,
    getModel,
    KnownProvider,
    Model,
    SimpleStreamOptions,
    streamSimple,
    ToolCall,
} from '@earendil-works/pi-ai'

import type { ReasoningEffort } from '@posthog/agent-shared'

export interface PiClient {
    /**
     * Run one assistant turn with the given model + context. Returns the raw
     * AssistantMessage from pi-ai — the runner pushes it into the conversation
     * and inspects `content[]` for `toolCall` blocks.
     */
    invoke(model: Model<string>, context: Context, opts?: InvokeOpts): Promise<AssistantMessage>
    /**
     * Streaming variant of `invoke()`. Returns an `AsyncIterable<StreamDelta>`
     * that yields incremental text / thinking / tool-call events as pi-ai
     * produces them, terminating with a single `{ type: 'end', assistantMessage }`
     * event carrying the fully-materialized turn (same shape `invoke()`
     * resolves to).
     *
     * v0b lands the surface. The runner still defaults to `invoke()`;
     * `run-turn.ts` switches over in v1 (see `streaming-and-reasoning.md`).
     */
    stream(model: Model<string>, context: Context, opts?: StreamOpts): AsyncIterable<StreamDelta>
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

export type StreamOpts = InvokeOpts

/**
 * Normalised stream event the runner consumes. Property shapes (`text` not
 * `delta`, extracted `id` + `name` on toolcall events, …) are deliberately
 * opinionated so consumers don't have to learn pi-ai's internal event union.
 *
 * Field semantics mirror the spec in `streaming-and-reasoning.md` §4:
 *   - `text_delta`, `thinking_delta`: incremental content.
 *   - `toolcall_start`: id + name available; arguments still streaming.
 *   - `toolcall_delta`: raw JSON arg chunks; concatenation isn't always valid
 *      JSON mid-stream — wait for `toolcall_end` to dispatch.
 *   - `toolcall_end`: fully-formed `arguments` object — safe to dispatch.
 *   - `end`: the terminal event, exactly once per stream. Carries the
 *      `AssistantMessage` so the consumer doesn't have to re-derive it
 *      from the deltas (pi-ai already materialised it on its end).
 */
export type StreamDelta =
    | { type: 'text_delta'; text: string }
    | { type: 'thinking_delta'; thinking: string }
    | { type: 'toolcall_start'; id: string; name: string }
    | { type: 'toolcall_delta'; id: string; argsDelta: string }
    | { type: 'toolcall_end'; id: string; name: string; arguments: Record<string, unknown> }
    | { type: 'end'; assistantMessage: AssistantMessage }

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

    stream(model: Model<string>, context: Context, opts?: StreamOpts): AsyncIterable<StreamDelta> {
        const streamOpts: SimpleStreamOptions = {
            apiKey: opts?.apiKey ?? this.defaultApiKey,
            maxTokens: opts?.maxTokens,
            temperature: opts?.temperature,
            signal: opts?.signal,
            reasoning: opts?.reasoning,
        }
        const piStream = streamSimple(model, context, streamOpts)
        return translatePiAiEventStream(piStream)
    }
}

/**
 * Translate pi-ai's `AssistantMessageEvent` union into our normalised
 * `StreamDelta` shape. The mapping is mostly mechanical; the only complexity
 * is `toolcall_start` — pi-ai signals "a tool-call block is starting at
 * contentIndex N" but the id + name live on `partial.content[N]`, so we
 * read them out of the partial.
 *
 * `text_start` / `text_end` / `thinking_start` / `thinking_end` are dropped
 * — the per-block boundaries don't survive normalisation, and consumers
 * either don't care (they're building UI from concatenated deltas) or read
 * the final `assistantMessage` from the `end` event.
 */
async function* translatePiAiEventStream(piStream: AsyncIterable<AssistantMessageEvent>): AsyncIterable<StreamDelta> {
    for await (const event of piStream) {
        switch (event.type) {
            case 'text_delta':
                yield { type: 'text_delta', text: event.delta }
                continue
            case 'thinking_delta':
                yield { type: 'thinking_delta', thinking: event.delta }
                continue
            case 'toolcall_start': {
                const block = event.partial.content[event.contentIndex]
                if (block && block.type === 'toolCall') {
                    yield { type: 'toolcall_start', id: block.id, name: block.name }
                }
                continue
            }
            case 'toolcall_delta': {
                const block = event.partial.content[event.contentIndex]
                if (block && block.type === 'toolCall') {
                    yield { type: 'toolcall_delta', id: block.id, argsDelta: event.delta }
                }
                continue
            }
            case 'toolcall_end': {
                const tc: ToolCall = event.toolCall
                yield { type: 'toolcall_end', id: tc.id, name: tc.name, arguments: tc.arguments }
                continue
            }
            case 'done':
                yield { type: 'end', assistantMessage: event.message }
                return
            case 'error':
                yield { type: 'end', assistantMessage: event.error }
                return
            default:
                // start / *_start / *_end events we deliberately skip — see
                // comment above translatePiAiEventStream.
                continue
        }
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
