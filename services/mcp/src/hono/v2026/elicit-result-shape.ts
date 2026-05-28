/**
 * Lightweight type-guard for incoming `inputResponses` entries.
 *
 * The dispatcher receives `inputResponses: { [key]: unknown }` from the
 * client and must verify each entry conforms to `ElicitResult` before
 * caching it in `requestState` or returning it from `requestInput`.
 *
 * Re-uses the SDK's Zod schema so the shape tracks the spec.
 */

import { ElicitResultSchema, type ElicitResult } from '@modelcontextprotocol/sdk/types.js'

export function isElicitResult(value: unknown): value is ElicitResult {
    return ElicitResultSchema.safeParse(value).success
}
