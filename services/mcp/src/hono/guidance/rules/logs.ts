import { emptyResultRule, hasArg } from '../empty-result-rule'
import type { GuidanceCall } from '../engine'
import type { GuidanceRule } from '../rule-schema'

const QUERY_LOGS_TOOL = 'query-logs'
const VALUE_TOOLS = ['logs-attributes-list', 'logs-attribute-values-list']

const LOGS_FILTERS = ['serviceNames', 'severityLevels', 'filterGroup']

// The tool takes every parameter inside `query`.
function queryOf(call: GuidanceCall): GuidanceCall {
    const query = call.args?.query
    return { ...call, args: typeof query === 'object' && query !== null ? (query as Record<string, unknown>) : {} }
}

function filtersIn(call: GuidanceCall): string[] {
    return LOGS_FILTERS.filter((filter) => hasArg(queryOf(call), filter))
}

function searches(call: GuidanceCall): boolean {
    return hasArg(queryOf(call), 'searchTerm')
}

function logsRule(rule: {
    id: string
    when: (call: GuidanceCall) => boolean
    hasLogs: boolean
    requiresTool?: string[]
    suppressIfCalled?: string[]
    text: GuidanceRule['text']
}): GuidanceRule {
    return emptyResultRule({
        id: rule.id,
        tool: QUERY_LOGS_TOOL,
        needsEventData: false,
        requiresTool: [QUERY_LOGS_TOOL, ...(rule.requiresTool ?? [])],
        suppressIfCalled: rule.suppressIfCalled,
        when: async ({ call, productState }) =>
            !hasArg(queryOf(call), 'after') && rule.when(call) && (await productState.hasLogs()) === rule.hasLogs,
        text: rule.text,
    })
}

const rules: GuidanceRule[] = [
    logsRule({
        id: 'logs-empty-to-no-logs',
        hasLogs: false,
        when: () => true,
        requiresTool: ['docs-search'],
        suppressIfCalled: ['docs-search'],
        text: [
            'PostHog holds no logs for this project, in any service or date range.',
            'This result does not show whether a service tries to send logs.',
            'PostHog receives logs over OTLP, and `docs-search` finds the setup and troubleshooting steps.',
        ].join(' '),
    }),
    logsRule({
        id: 'logs-empty-to-search',
        hasLogs: true,
        when: searches,
        requiresTool: VALUE_TOOLS,
        text: (call) =>
            [
                'This project has logs, but none matched this query in this date range.',
                `This call filtered on ${['searchTerm', ...filtersIn(call)].map((filter) => `\`${filter}\``).join(', ')}.`,
                '`searchTerm` matches the log body only, as one substring, and ignores case.',
                'It does not match service names, attributes or severity, and several words match only in that exact order.',
                'A value held in an attribute needs a `filterGroup` filter: `logs-attributes-list` lists the keys and `logs-attribute-values-list` lists the values.',
            ].join(' '),
    }),
    logsRule({
        id: 'logs-empty-to-filters',
        hasLogs: true,
        when: (call) => !searches(call) && filtersIn(call).length > 0,
        requiresTool: VALUE_TOOLS,
        text: (call) =>
            [
                'This project has logs, but none matched this query in this date range.',
                `This call filtered on ${filtersIn(call)
                    .map((filter) => `\`${filter}\``)
                    .join(', ')}.`,
                'A service name, severity or attribute value that does not exist matches nothing.',
                '`logs-attribute-values-list` lists the values in use, with `key: "service.name"` and `attribute_type: "resource"` for services.',
            ].join(' '),
    }),
    logsRule({
        id: 'logs-empty-to-range',
        hasLogs: true,
        when: (call) => !searches(call) && filtersIn(call).length === 0,
        text: ['This project has logs, but this date range has none.', 'The result covers only this range.'].join(' '),
    }),
]

export default rules
