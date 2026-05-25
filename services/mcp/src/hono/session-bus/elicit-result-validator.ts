/**
 * Validation for `ElicitResult` payloads delivered through the session bus.
 *
 * The bus is intentionally schema-agnostic — it stores opaque JSON. The
 * gateway is responsible for asserting the response actually matches the
 * MCP `ElicitResult` shape before handing it to a caller who's awaiting an
 * elicit result.
 *
 * We reuse the SDK's Zod schema rather than hand-rolling: it stays in sync
 * with the upstream MCP spec for free. (Zod, not AJV — there's no
 * `new Function()` involved either way, but reusing the SDK's exported
 * schema keeps us aligned with the protocol version the SDK targets.)
 */

import { ElicitResultSchema, type ElicitResult } from '@modelcontextprotocol/sdk/types.js'

import { SessionBusUnhealthyError } from './errors'

export function validateElicitResult(raw: unknown): ElicitResult {
    const parsed = ElicitResultSchema.safeParse(raw)
    if (!parsed.success) {
        // Treat a bad payload as a bus-level problem rather than a normal
        // decline/cancel. If we ever see this in production it means a
        // client is sending malformed elicitation responses — that's a
        // protocol violation, not a user choice. Fail closed.
        throw new SessionBusUnhealthyError(
            `Elicitation response payload did not match the ElicitResult schema: ${parsed.error.message}`,
            { cause: parsed.error }
        )
    }
    return parsed.data
}
