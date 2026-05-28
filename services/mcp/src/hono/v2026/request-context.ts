/**
 * `RequestContext` adapter for the v2026 pipeline.
 *
 * Mirrors the legacy `RequestContext` API but its `Context.requestInput`
 * implementation does not push over SSE / park on a bus — it consults the
 * incoming `inputResponses` plus the prior-rounds answers decoded from
 * `requestState`. If the key has an answer, return it; otherwise throw
 * `InputRequiredSignal` for the dispatcher to convert into an
 * `InputRequiredResult`.
 *
 * The legacy `Context.elicit` field is left `undefined` on this pipeline so
 * that tools still using the legacy API see "no capability" and fall back
 * the same way they would for a client that didn't declare elicitation
 * support. Tools should migrate to `requestInput` to keep working under
 * both protocol versions.
 */

import type { ElicitResult } from '@modelcontextprotocol/sdk/types.js'

import type { Context, RequestInputParams } from '@/tools/types'

import type { RequestContext as LegacyRequestContext } from '../request-context'
import { isElicitResult } from './elicit-result-shape'
import { InputRequiredSignal } from './input-required-signal'

/**
 * Map of `requestInput` key → response. Built from:
 *   - The decoded prior `requestState`'s answers (rounds 0..N-1).
 *   - The current request's `inputResponses` field (this round's answers).
 * Merged together; later writes win on key collision.
 */
export type AnswerMap = Record<string, ElicitResult>

export interface V2026RequestContextDeps {
    /** The legacy RequestContext provides everything except elicit/requestInput. */
    legacy: LegacyRequestContext
    /** Answers seen so far across all rounds. */
    answers: AnswerMap
}

export class V2026RequestContext {
    constructor(private readonly deps: V2026RequestContextDeps) {}

    /**
     * Build the `Context` object handed to tool handlers. Reuses everything
     * the legacy context provides (api, cache, stateManager, sessionManager,
     * getDistinctId, trackEvent) and overrides `elicit` (always undefined)
     * + `requestInput` (v2026 semantics).
     */
    async getContext(): Promise<Context> {
        const base = await this.deps.legacy.getContext()
        const answers = this.deps.answers
        const ctx: Context = {
            api: base.api,
            cache: base.cache,
            env: base.env,
            stateManager: base.stateManager,
            sessionManager: base.sessionManager,
            getDistinctId: base.getDistinctId,
            trackEvent: base.trackEvent,
        }
        // The v2026 pipeline does not push elicitation/create — leave the
        // legacy field undefined so any code still branching on it falls
        // back gracefully.
        Object.defineProperty(ctx, 'requestInput', {
            enumerable: true,
            configurable: false,
            value: async (params: RequestInputParams): Promise<ElicitResult> => {
                const existing = answers[params.key]
                if (existing !== undefined) {
                    return existing
                }
                throw new InputRequiredSignal(params.key, {
                    message: params.message,
                    requestedSchema: params.requestedSchema,
                })
            },
        })
        return ctx
    }
}

export { isElicitResult }
