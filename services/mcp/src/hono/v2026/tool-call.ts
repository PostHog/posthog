/**
 * v2026 `tools/call` dispatch.
 *
 * Stateless continuation-passing: the tool handler runs with a
 * v2026-flavored `Context` whose `requestInput` resolves answers from the
 * incoming `inputResponses` + decoded `requestState`, or throws
 * `InputRequiredSignal` to surface a new prompt. The signal is caught
 * here, encoded into a fresh `requestState`, and returned as
 * `InputRequiredResult`. Any server instance can pick up the retry.
 */

import { JSONRPC_VERSION, type JSONRPCRequest } from '@modelcontextprotocol/sdk/types.js'

import type { RequestProperties } from '@/lib/request-properties'

import type { ProtocolStrategy, ToolCallStrategy } from '../protocol-strategy'
import type { ResolvedState } from '../request-state-resolver'
import type { ToolExecutor } from '../tool-executor'
import { isElicitResult } from './elicit-result-shape'
import { RequestStateError, RequestStateExpired, invalidParams, V2026ProtocolError } from './errors'
import { isInputRequiredSignal } from './input-required-signal'
import {
    v2026InputRequiredRoundTrips,
    v2026RequestStateDecodeTotal,
    v2026RequestStateExpiredTotal,
    v2026RequestsTotal,
} from './metrics'
import { V2026PreDispatch } from './pre-dispatch'
import { V2026RequestContext, type AnswerMap } from './request-context'
import { RequestStateCodec } from './request-state'

export interface V2026ToolCallDeps {
    codec: RequestStateCodec
    toolExecutor: ToolExecutor
}

export class V2026ToolCallStrategy implements ToolCallStrategy {
    constructor(private readonly deps: V2026ToolCallDeps) {}

    async dispatchToolsCall(
        request: JSONRPCRequest,
        props: RequestProperties,
        state: ResolvedState,
        _signal: AbortSignal
    ): Promise<Response> {
        const params = (request.params ?? {}) as Record<string, unknown>
        const toolName = params['name']
        if (typeof toolName !== 'string') {
            throw invalidParams('tools/call params.name must be a string')
        }

        // Decode any prior requestState. Failures are reported as
        // INVALID_PARAMS — the client can drop the requestState and start a
        // fresh tool call.
        let priorAnswers: AnswerMap = {}
        let priorRound = 0
        const incomingState = params['requestState']
        if (incomingState !== undefined) {
            if (typeof incomingState !== 'string') {
                throw invalidParams('requestState must be a string')
            }
            try {
                const claims = this.deps.codec.decode(incomingState, props.userHash, toolName)
                v2026RequestStateDecodeTotal.inc({ result: 'ok' })
                priorRound = claims.round
                priorAnswers = decodeAnswersFromClaims(claims.payload)
            } catch (err) {
                if (err instanceof RequestStateError) {
                    v2026RequestStateDecodeTotal.inc({ result: err.metricLabel })
                    if (err instanceof RequestStateExpired) {
                        v2026RequestStateExpiredTotal.inc()
                    }
                    throw invalidParams(`requestState rejected: ${err.message}`)
                }
                throw err
            }
        }

        const newAnswers = parseInputResponses(params['inputResponses'])
        const combinedAnswers: AnswerMap = { ...priorAnswers, ...newAnswers }

        // Wrap the resolved context with the v2026 adapter so the handler
        // sees a `requestInput` that resolves from `combinedAnswers` (or
        // throws InputRequiredSignal for unanswered keys).
        const v2026Ctx = new V2026RequestContext({ legacy: state.reqCtx, answers: combinedAnswers })
        const augmentedState: ResolvedState = { ...state, context: await v2026Ctx.getContext() }

        const callParams = { name: toolName, arguments: params['arguments'] }

        let handlerResult: unknown
        try {
            handlerResult = await this.deps.toolExecutor.handleToolCall(callParams, props, augmentedState)
        } catch (err) {
            if (isInputRequiredSignal(err)) {
                const round = priorRound + 1
                const nextState = this.deps.codec.encode({
                    sub: props.userHash,
                    tool: toolName,
                    round,
                    payload: { priorAnswers: combinedAnswers },
                })
                v2026RequestsTotal.inc({ outcome: 'input_required' })
                return jsonResponse({
                    jsonrpc: JSONRPC_VERSION,
                    id: request.id,
                    result: {
                        resultType: 'input_required',
                        inputRequests: {
                            [err.key]: {
                                method: 'elicitation/create',
                                params: {
                                    mode: 'form',
                                    message: err.elicitParams.message,
                                    requestedSchema: err.elicitParams.requestedSchema,
                                },
                            },
                        },
                        requestState: nextState,
                    },
                })
            }
            throw err
        }

        v2026RequestsTotal.inc({ outcome: 'complete' })
        v2026InputRequiredRoundTrips.observe(priorRound + 1)
        return jsonResponse({
            jsonrpc: JSONRPC_VERSION,
            id: request.id,
            result: {
                resultType: 'complete',
                ...(typeof handlerResult === 'object' && handlerResult !== null
                    ? handlerResult
                    : { value: handlerResult }),
            },
        })
    }
}

function decodeAnswersFromClaims(payload: unknown): AnswerMap {
    if (payload === null || typeof payload !== 'object') {
        return {}
    }
    const obj = payload as Record<string, unknown>
    const priorAnswers = obj['priorAnswers']
    if (priorAnswers === null || typeof priorAnswers !== 'object') {
        return {}
    }
    const result: AnswerMap = {}
    for (const [key, value] of Object.entries(priorAnswers as Record<string, unknown>)) {
        if (isElicitResult(value)) {
            result[key] = value
        }
    }
    return result
}

function parseInputResponses(value: unknown): AnswerMap {
    if (value === undefined || value === null) {
        return {}
    }
    if (typeof value !== 'object' || Array.isArray(value)) {
        throw invalidParams('inputResponses must be an object')
    }
    const result: AnswerMap = {}
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
        if (!isElicitResult(entry)) {
            throw invalidParams(`inputResponses.${key} is not a valid ElicitResult`)
        }
        result[key] = entry
    }
    return result
}

function jsonResponse(body: Record<string, unknown>): Response {
    return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
    })
}

/** Compose a complete `ProtocolStrategy` for `2026-07-28`. */
export function buildV2026Strategy(deps: {
    codec: RequestStateCodec
    toolExecutor: ToolExecutor
    handshake: import('./handshake').V2026HandshakeStrategy
}): ProtocolStrategy {
    return {
        version: 'v2026',
        allowBatches: false,
        preDispatch: new V2026PreDispatch(),
        handshake: deps.handshake,
        toolCall: new V2026ToolCallStrategy({ codec: deps.codec, toolExecutor: deps.toolExecutor }),
    }
}

// Re-export for the protocol-strategy interface assignability check in tests.
export type { V2026ProtocolError }
