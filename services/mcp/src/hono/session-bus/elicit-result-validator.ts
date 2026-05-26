/**
 * Validation for `ElicitResult` payloads delivered through the session bus.
 *
 * The bus is schema-agnostic — it stores opaque JSON shaped however the
 * streamable handler classified the inbound POST. Three shapes can arrive:
 *
 * 1. A valid `ElicitResult` (`{ action, content? }`) — the user accepted,
 *    declined, or canceled. Return it.
 * 2. A JSON-RPC error envelope (`{ error: { code, message, ... } }`) — the
 *    client is signalling at the protocol layer that it can't handle the
 *    request (typically `-32601 Method not found` for clients that didn't
 *    advertise elicitation support, or `-32602 Invalid params` for mode
 *    mismatches). This is a normal, expected protocol signal — surface it
 *    as `ElicitationNotSupportedError` so callers can fall back gracefully
 *    and observability doesn't treat it as a bus health incident.
 * 3. Anything else (malformed, missing required fields, wrong types) is a
 *    genuine bus health problem and stays under `SessionBusUnhealthyError`.
 */

import { ElicitResultSchema, type ElicitResult } from '@modelcontextprotocol/sdk/types.js'

import { ElicitationNotSupportedError, SessionBusUnhealthyError } from './errors'

interface JsonRpcErrorEnvelope {
    error: {
        code: number
        message: string
    }
}

export function validateElicitResult(raw: unknown): ElicitResult {
    const jsonRpcError = asJsonRpcErrorEnvelope(raw)
    if (jsonRpcError !== undefined) {
        throw new ElicitationNotSupportedError(jsonRpcError.error.code, jsonRpcError.error.message)
    }
    const parsed = ElicitResultSchema.safeParse(raw)
    if (!parsed.success) {
        throw new SessionBusUnhealthyError(
            `Elicitation response payload did not match the ElicitResult schema: ${parsed.error.message}`,
            { cause: parsed.error }
        )
    }
    return parsed.data
}

function asJsonRpcErrorEnvelope(raw: unknown): JsonRpcErrorEnvelope | undefined {
    if (raw === null || typeof raw !== 'object') {
        return undefined
    }
    const obj = raw as Record<string, unknown>
    const error = obj['error']
    if (error === null || typeof error !== 'object') {
        return undefined
    }
    const errObj = error as Record<string, unknown>
    if (typeof errObj['code'] !== 'number' || typeof errObj['message'] !== 'string') {
        return undefined
    }
    return { error: { code: errObj['code'], message: errObj['message'] } }
}
