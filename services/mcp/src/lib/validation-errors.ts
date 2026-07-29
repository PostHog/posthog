import { z } from 'zod'

/** Turns a Zod validation failure into a short, field-named message the model
 *  can act on. Without it, a missing/`undefined` path segment slips through to
 *  the HTTP layer and the API returns a generic 404 that reads as "entity does
 *  not exist" — steering recovery toward re-checking the ID rather than the
 *  malformed parameter.
 *
 *  Callers should `safeParse(input, { reportInput: true })` so `issue.input`
 *  distinguishes a missing required field from a present-but-wrong one (the
 *  key is absent without the option, and the check degrades to the wrong-type
 *  message). `reportInput` embeds raw input values in the ZodError, including
 *  its `.message` — keep the error local; never log or capture it. */
export function formatInputValidationError(toolName: string, error: z.ZodError): string {
    const parts = error.issues.map((issue) => {
        const path = issue.path.map(String).join('.')
        if (issue.code === 'invalid_type') {
            if ('input' in issue && issue.input === undefined) {
                return `missing required parameter: ${path}`
            }
            return `parameter "${path}" must be of type ${issue.expected}`
        }
        if (issue.code === 'unrecognized_keys') {
            return `unexpected ${issue.keys.length > 1 ? 'properties' : 'property'}: ${issue.keys.join(', ')}`
        }
        // A too-long string names the limit and the input's actual length so the
        // agent knows how much to trim (zod's default names only the limit).
        // Surfaces the LENGTH only, never the value: the message is returned to
        // the caller and recorded as the analytics error_message. `issue.input`
        // is only present under `reportInput: true`; without it, or for
        // non-string origins, fall through to zod's limit-naming default.
        if (issue.code === 'too_big' && issue.origin === 'string' && typeof issue.input === 'string') {
            return `parameter "${path}" is too long: ${issue.input.length} characters (max ${issue.maximum})`
        }
        return path ? `parameter "${path}": ${issue.message}` : issue.message
    })
    return `Invalid input for "${toolName}": ${[...new Set(parts)].join('; ')}`
}

/** Caps on what we record so a single failure can't blow up analytics cardinality. */
const MAX_VALIDATION_DESCRIPTORS = 20
const MAX_KEY_LENGTH = 64

/**
 * Derives a value-free descriptor of a validation failure for telemetry, so a
 * contract regression (agents sending a field name the schema doesn't accept) is
 * diagnosable from the `$mcp_tool_call` event alone — without ever recording the
 * request payload.
 *
 * `fields` are the offending top-level field + issue code (e.g. `orgId:invalid_type`);
 * for a union rejection the path is empty and it reads `(root):invalid_union`, which
 * is why `inputKeys` — the top-level keys the caller actually sent — carries the real
 * signal there (it surfaces the unaccepted alias, e.g. `organizationId`). `inputKeys`
 * is empty when the caller's payload isn't at hand (e.g. a stray ZodError classified
 * after the fact in `handleToolError`).
 *
 * Records only structural information (field names, issue codes). It never touches
 * input VALUES: the ZodError embeds raw values in `issue.input` and `.message` (see
 * `formatInputValidationError`), so we read `issue.path[0]`/`issue.code` and the
 * input's own key names only.
 */
export function describeValidationError(
    error: z.ZodError,
    input?: Record<string, unknown>
): { fields: string[]; inputKeys: string[] } {
    const fields = [
        ...new Set(
            error.issues.map((issue) => {
                const top = issue.path.length ? String(issue.path[0]) : '(root)'
                return `${top.slice(0, MAX_KEY_LENGTH)}:${issue.code}`
            })
        ),
    ].slice(0, MAX_VALIDATION_DESCRIPTORS)
    const inputKeys = Object.keys(input ?? {})
        .sort()
        .slice(0, MAX_VALIDATION_DESCRIPTORS)
        .map((key) => key.slice(0, MAX_KEY_LENGTH))
    return { fields, inputKeys }
}

/**
 * Walks `Error.cause` chains for a ZodError. A `.parse()` inside a tool handler
 * (or on data the API returned) throws one that no validation gate caught, and
 * zod v4's `ZodError.message` IS the JSON-stringified issue array — several
 * hundred lines of nested `invalid_union` objects. Left unclassified it reaches
 * `handleToolError`'s fallthrough, which returns `error.message` to the model and
 * captures it as an exception, so the dump lands both in the user's chat and in
 * error tracking.
 *
 * Duck-typed rather than `instanceof`-only so a ZodError minted by a second copy
 * of zod (a transitive dependency resolving its own version) is still recognized.
 */
export function findZodError(error: unknown): z.ZodError | undefined {
    let current: unknown = error
    const seen = new Set<unknown>()
    while (current && !seen.has(current)) {
        if (isZodError(current)) {
            return current
        }
        seen.add(current)
        current = current instanceof Error ? (current as Error & { cause?: unknown }).cause : undefined
    }
    return undefined
}

function isZodError(value: unknown): value is z.ZodError {
    if (value instanceof z.ZodError) {
        return true
    }
    return (
        value instanceof Error &&
        value.name === 'ZodError' &&
        Array.isArray((value as Error & { issues?: unknown }).issues)
    )
}
