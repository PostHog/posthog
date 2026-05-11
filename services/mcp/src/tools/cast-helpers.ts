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
