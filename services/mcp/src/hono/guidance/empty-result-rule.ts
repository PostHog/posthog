import type { GuidanceCall } from './engine'
import type { GuidanceCondition, GuidanceRule } from './rule-schema'

export const MCP_GUIDANCE_EMPTY_STATES_FLAG = 'mcp-guidance-empty-states'

export function hasArg(call: GuidanceCall, name: string): boolean {
    const value = call.args?.[name]
    return value !== undefined && value !== null && value !== '' && !(Array.isArray(value) && value.length === 0)
}

// An empty later page only means the agent read past the last row.
// Some tools take every parameter inside `query`, so the cursor can be there.
function isLaterPage(call: GuidanceCall): boolean {
    const query = call.args?.query
    const nested = typeof query === 'object' && query !== null ? (query as Record<string, unknown>) : {}
    return [call.args ?? {}, nested].some(
        (args) => (typeof args.offset === 'number' && args.offset > 0) || hasArg({ ...call, args }, 'after')
    )
}

export function emptyResultRule(rule: {
    id: string
    tool: string
    flag?: string
    when: GuidanceCondition
    text: GuidanceRule['text']
    maxPerSession?: number
    suppressIfCalled?: string[]
    requiresTool?: string[]
    /** Set to false for data that a project can send without any events, such as logs. */
    needsEventData?: boolean
}): GuidanceRule {
    return {
        id: rule.id,
        flag: rule.flag ?? MCP_GUIDANCE_EMPTY_STATES_FLAG,
        trigger: { tool: rule.tool, resultEmpty: true, outcome: 'success', presets: ['user'] },
        threshold: 1,
        maxPerSession: rule.maxPerSession ?? 1,
        suppressIfCalled: rule.suppressIfCalled ?? [],
        requiresTool: rule.requiresTool ?? [rule.tool],
        // A project with no data at all gets no notice, so a product lookup never runs for it.
        condition: async (input) =>
            !isLaterPage(input.call) &&
            (rule.needsEventData === false || (await input.productState.hasIngestedData()) === true) &&
            (await rule.when(input)),
        text: rule.text,
    }
}
