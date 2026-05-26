/**
 * Transitional backward-compat parameter aliases for tools whose input
 * schema briefly exposed a different parameter name than what the docs
 * (and any long-lived agents) expected. Each entry maps an alias the
 * caller might send to the canonical name the tool's Zod schema requires.
 *
 * Apply this rewrite **before** `tool.schema.safeParse(params)` and pass
 * the rewritten object to the tool's handler. The schema itself stays
 * pinned to the canonical name — we just normalize the input on the way
 * in.
 *
 * Each entry must carry a sunset date in the comment. Remove the entry
 * (and the corresponding test) on or after that date.
 */
export const TOOL_PARAM_ALIASES: Record<string, Record<string, string>> = {
    // PR #58697 (merged 2026-05-26) renamed the URL kwarg on
    // `llma-skill-get` / `llma-skill-update` from `skill_name` to
    // `skill_identifier`. Issue #60049 reverted it; this alias lets
    // agents that adopted `skill_identifier` during the regression
    // window keep working without an immediate forced upgrade.
    // Sunset: 2026-08-01.
    'llma-skill-get': { skill_identifier: 'skill_name' },
    'llma-skill-update': { skill_identifier: 'skill_name' },
}

export function applyBackwardCompatParamAliases<TParams>(toolName: string, params: TParams): TParams {
    const aliases = TOOL_PARAM_ALIASES[toolName]
    if (!aliases || !params || typeof params !== 'object') {
        return params
    }
    const source = params as Record<string, unknown>
    let rewritten: Record<string, unknown> | null = null
    for (const [from, to] of Object.entries(aliases)) {
        if (source[from] !== undefined && source[to] === undefined) {
            rewritten = rewritten ?? { ...source }
            rewritten[to] = source[from]
            delete rewritten[from]
        }
    }
    return (rewritten ?? params) as TParams
}
