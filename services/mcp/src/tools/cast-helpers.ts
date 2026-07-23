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
export const normalizeParamAliases =
    (aliasMap: Record<string, readonly string[]>) =>
    (input: unknown): unknown => {
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
