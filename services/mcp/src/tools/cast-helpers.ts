import { z } from 'zod'

/**
 * Input casts for permissive zod schemas at the MCP tool boundary.
 *
 * MCP clients — especially LLM agents — sometimes send numeric primitives
 * as strings (e.g. `id: "123"` instead of `id: 123`). Production traces
 * showed this consistently across experiment tools and a handful of others
 * (`project-get`, `dashboard-get`, etc.). Rather than globally relaxing
 * every numeric field via `z.coerce.number()` — which would also accept
 * surprising inputs like `true → 1` and `null → 0` — these casts apply a
 * narrow, opt-in conversion that only touches strings whose contents are
 * unambiguously a base-10 integer. Leading zeros (e.g. `"007"`) are
 * accepted and parse to the obvious value (7).
 *
 * Compose via `z.preprocess(castStringToInt, originalSchema)` so the
 * field's existing description, integer constraint, and bounds are
 * preserved. Anything that isn't a stringified integer passes through
 * unchanged so zod can still reject true type mismatches with its honest
 * error message.
 *
 * Wired up declaratively via `param_overrides: { id: { cast: 'string-int' } }`
 * in product `tools.yaml` files — see services/mcp/scripts/generate-tools.ts.
 */

/** Cast strings that look like a base-10 integer (e.g. "123", "-7", "007") to a number; pass everything else through. */
export const castStringToInt = (v: unknown): unknown => {
    // Regex: optional minus sign followed by one or more digits
    if (typeof v === 'string' && /^-?\d+$/.test(v)) {
        return Number(v)
    }
    return v
}

/**
 * Cast a boolean to its lowercase string form; pass everything else through.
 *
 * Some string query params read as booleans to an agent — a filter named
 * `enabled` is the clearest case — so agents send `true` where the schema
 * wants a string. The backend filters already accept `true` / `false` as
 * aliases, so the only thing standing between the call and a result is the
 * tool boundary. Anything that isn't a boolean passes through unchanged, so
 * zod still rejects true type mismatches.
 *
 * Wired up declaratively via `param_overrides: { enabled: { cast: 'boolean-string' } }`
 * in product `tools.yaml` files — see services/mcp/scripts/generate-tools.ts.
 */
export const castBooleanToString = (v: unknown): unknown => (typeof v === 'boolean' ? String(v) : v)

export const castObjectToJsonString = (v: unknown): unknown =>
    v !== null && typeof v === 'object' && !Array.isArray(v) ? JSON.stringify(v) : v

/**
 * Normalize alternate key spellings to a canonical param name before validation.
 *
 * Agents composing calls from scratch guess the identifier key from context —
 * production traces show `insight-get` receiving `insightId` / `short_id` /
 * `insight_id` / `shortId` where the schema requires `id`, and `insight-query`
 * receiving the reverse. Same failure mode the `orgId` aliases in
 * `OrganizationSetActiveSchema` exist for (see src/schema/tool-inputs.ts), but
 * for schemas with additional fields where a union of per-alias branches
 * doesn't scale.
 *
 * Compose via `z.preprocess(normalizeParamAliases({ id: ['insightId', ...] }), schema)`.
 * The canonical key wins when present; otherwise the first-listed alias with a
 * value wins. Alias keys are always removed so they never reach handlers or
 * `.strict()` validation. In zod 4's JSON Schema output (`io: 'input'`) a
 * preprocess renders as the wrapped schema, so the advertised schema still
 * shows only the canonical, required param.
 *
 * Wired up declaratively via `param_overrides: { id: { aliases: [...] } }` in
 * product `tools.yaml` files — see services/mcp/scripts/generate-tools.ts.
 */
export const normalizeParamAliases = (aliasMap: Record<string, readonly string[]>): ((input: unknown) => unknown) => {
    const normalize = (input: unknown): unknown => {
        if (input === null || typeof input !== 'object' || Array.isArray(input)) {
            return input
        }
        const record = input as Record<string, unknown>
        const hasAlias = Object.values(aliasMap).some((aliases) => aliases.some((alias) => alias in record))
        if (!hasAlias) {
            return input
        }
        const result = { ...record }
        for (const [canonical, aliases] of Object.entries(aliasMap)) {
            for (const alias of aliases) {
                if (alias in result) {
                    if (result[canonical] === undefined) {
                        result[canonical] = result[alias]
                    }
                    delete result[alias]
                }
            }
        }
        return result
    }
    ALIAS_MAPS.set(normalize, aliasMap)
    return normalize
}

/** Hyphenated UUID in any version, the shape of PostHog run / resource UUIDs. */
const UUID_SHAPE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

const looksLikeUuid = (v: unknown): boolean => typeof v === 'string' && UUID_SHAPE.test(v)

const looksLikeInt = (v: unknown): boolean =>
    (typeof v === 'number' && Number.isInteger(v)) || (typeof v === 'string' && /^-?\d+$/.test(v))

/**
 * Move a UUID an agent put under an integer-id param into the UUID param it
 * belongs to, before validation.
 *
 * October 2026 production traces show `experiment-metrics-recalculation-retrieve`
 * rejecting calls with "parameter 'id' must be of type number" because agents
 * pass the recalculation run UUID as `id` — the tool takes the experiment's
 * integer id as `id` and the run UUID as `recalculation_id`. The existing
 * `cast` / `aliases` overrides are per-param, so neither can express "this
 * value is for the other param".
 *
 * `redirects` maps the integer-id param → the UUID param. For each pair, when
 * the integer param holds a UUID-shaped string:
 * - UUID param absent → the UUID moves there and the integer param is removed,
 *   so validation fails only on the missing integer id, with that field's own
 *   description naming what to send.
 * - UUID param holds an integer (or integer string) → the two values swap, the
 *   call was right apart from the key assignment, and it proceeds.
 * - anything else → the input passes through untouched so zod rejects with its
 *   honest error.
 *
 * Wired up declaratively via `param_overrides: { id: { uuid_redirect: '...' } }`
 * in product `tools.yaml` files — see services/mcp/scripts/generate-tools.ts.
 * Composed inside the `normalizeParamAliases` wrapper, so alias keys are folded
 * to canonical names before the redirect looks at them.
 */
export const redirectMisplacedUuids = (redirects: Record<string, string>): ((input: unknown) => unknown) => {
    return (input: unknown): unknown => {
        if (input === null || typeof input !== 'object' || Array.isArray(input)) {
            return input
        }
        const record = input as Record<string, unknown>
        const applies = Object.entries(redirects).some(
            ([intParam, uuidParam]) =>
                looksLikeUuid(record[intParam]) && (record[uuidParam] === undefined || looksLikeInt(record[uuidParam]))
        )
        if (!applies) {
            return input
        }
        const result = { ...record }
        for (const [intParam, uuidParam] of Object.entries(redirects)) {
            if (!looksLikeUuid(result[intParam])) {
                continue
            }
            if (result[uuidParam] === undefined) {
                result[uuidParam] = result[intParam]
                delete result[intParam]
            } else if (looksLikeInt(result[uuidParam])) {
                const uuid = result[intParam]
                result[intParam] = result[uuidParam]
                result[uuidParam] = uuid
            }
        }
        return result
    }
}

/**
 * Alias maps keyed by the preprocess function that applies them. Telemetry reads the
 * map back off a tool's schema to record which alias a call carried, so the map has
 * one source of truth: the same `normalizeParamAliases(...)` call the schema uses.
 */
const ALIAS_MAPS = new WeakMap<(input: unknown) => unknown, Record<string, readonly string[]>>()

/** Deeper than any tool stacks `z.preprocess` today; bounds the walk over a malformed pipe chain. */
const MAX_PREPROCESS_DEPTH = 8

/**
 * The alias maps a schema applies, merged across nested `z.preprocess(normalizeParamAliases(...), ...)`
 * layers, or undefined when it applies none. Walks the pipe chain that `z.preprocess` builds
 * (`ZodPipe` with the transform on `.in`), the same way `schemaHasOutputFormat` walks `.out`.
 * Only a `normalizeParamAliases(...)` closure passed straight to `z.preprocess` is found; a tool
 * that calls it from inside its own preprocess function (`read-data-schema`) reads as alias-free.
 */
export function readParamAliases(schema: z.ZodType): Record<string, readonly string[]> | undefined {
    let merged: Record<string, readonly string[]> | undefined
    let current: unknown = schema
    for (let depth = 0; depth < MAX_PREPROCESS_DEPTH && current instanceof z.ZodPipe; depth++) {
        const transform = (current.in as { def?: { transform?: unknown } }).def?.transform
        const aliasMap =
            typeof transform === 'function' ? ALIAS_MAPS.get(transform as (input: unknown) => unknown) : undefined
        if (aliasMap) {
            // Outer layers normalise first, so their aliases come first for a shared canonical.
            merged ??= {}
            for (const [canonical, aliases] of Object.entries(aliasMap)) {
                merged[canonical] = [...new Set([...(merged[canonical] ?? []), ...aliases])]
            }
        }
        current = current.out
    }
    return merged
}

// A schema that transforms its input (other than alias folding) consumes keys on purpose,
// so comparing sent keys to the parsed result would report them as ignored.
export function reshapesInputBeyondAliases(schema: z.ZodType): boolean {
    let current: unknown = schema
    for (let depth = 0; depth < MAX_PREPROCESS_DEPTH && current instanceof z.ZodPipe; depth++) {
        const input = current.in as { def?: { transform?: unknown } }
        if (current.in instanceof z.ZodTransform) {
            const transform = input.def?.transform
            if (typeof transform !== 'function' || !ALIAS_MAPS.has(transform as (input: unknown) => unknown)) {
                return true
            }
        }
        if (current.out instanceof z.ZodTransform) {
            return true
        }
        current = current.out
    }
    return current instanceof z.ZodUnion
}
