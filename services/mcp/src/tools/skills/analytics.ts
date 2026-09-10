/**
 * Analytics properties identifying which stored skill a skill-* read touched.
 *
 * Reading a stored skill is one of the most common MCP tool calls, but until now
 * `$mcp_tool_call` recorded only that *a* skill was read, never which one — so
 * "which skills does anyone actually use" was unanswerable, and the skills
 * product had to fall back on publish-recency and version churn as a proxy.
 *
 * Scope is deliberately narrow:
 *
 *  - **Reads only.** Writes already emit `llma skill *` server-side from
 *    `products/skills/backend/api/skills.py`; stamping them here would give two
 *    disagreeing sources for the same fact.
 *  - **No file path.** `$mcp_tool_name` already distinguishes a body read from a
 *    bundled-file read, which is the signal that matters (did progressive
 *    disclosure get exercised). The path itself buys nothing yet.
 *  - **Value-free by construction**, the rule `execCommandAnalyticsProperties`
 *    states: a name is recorded only if it matches the shape the store enforces
 *    at creation. Anything else is the agent's own text and is dropped rather
 *    than echoed into analytics.
 */

/** The store's own constraint: lowercase alphanumerics and hyphens, max 64 chars.
 *  Enforced at skill creation, so a value outside it never named a real skill. */
const RECORDABLE_SKILL_NAME = /^[a-z0-9][a-z0-9-]{0,63}$/

/** Read tools that name a single skill. The `llma-skill-*` entries are the
 *  deprecated aliases from `deprecatedAliases.ts`, which reach analytics under
 *  their own name and would otherwise be a silent hole in the data. */
const SKILL_READ_TOOLS = new Set(['skill-get', 'skill-file-get', 'llma-skill-get', 'llma-skill-file-get'])

/** Only `skill-get` pages a body; the offset is meaningless on the others. */
const BODY_PAGINATED_TOOLS = new Set(['skill-get', 'llma-skill-get'])

function recordableSkillName(value: unknown): string | undefined {
    return typeof value === 'string' && RECORDABLE_SKILL_NAME.test(value) ? value : undefined
}

/** A whole, non-negative offset — anything else says more about a malformed call
 *  than about paging, and a wrong number here would be read as a real page. */
function recordableBodyOffset(value: unknown): number | undefined {
    if (typeof value !== 'number' && typeof value !== 'string') {
        return
    }
    const offset = Number(value)
    return Number.isSafeInteger(offset) && offset >= 0 ? offset : undefined
}

/**
 * Properties describing the skill a read tool targeted: `$mcp_skill_name`, plus
 * `$mcp_skill_body_offset` on the paginated body read.
 *
 * The offset exists so paging does not read as usage. `skill-get` returns a body
 * in slices, and an agent reading one skill emits several calls that differ only
 * by offset — so `count()` overstates loads several-fold. With the offset stamped,
 * first-page calls are the load count and the rest are visibly continuations.
 *
 * `args` is whatever the caller has: parsed tool arguments in direct mode, or the
 * output of `parseExecCallInnerArgs` in single-exec mode. Malformed input yields
 * no properties rather than throwing — analytics must never break a tool call.
 */
export function skillAnalyticsProperties(toolName: string | undefined, args: unknown): Record<string, unknown> {
    if (!toolName || !SKILL_READ_TOOLS.has(toolName)) {
        return {}
    }
    if (args === null || typeof args !== 'object' || Array.isArray(args)) {
        return {}
    }
    const { skill_name: skillNameArg, body_offset: bodyOffsetArg } = args as Record<string, unknown>
    const skillName = recordableSkillName(skillNameArg)
    if (!skillName) {
        return {}
    }
    const bodyOffset = BODY_PAGINATED_TOOLS.has(toolName) ? recordableBodyOffset(bodyOffsetArg) : undefined
    return {
        $mcp_skill_name: skillName,
        ...(bodyOffset !== undefined ? { $mcp_skill_body_offset: bodyOffset } : {}),
    }
}
