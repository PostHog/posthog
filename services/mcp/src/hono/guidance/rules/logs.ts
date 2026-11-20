import { emptyResultRule } from '../empty-result-rule'
import type { GuidanceRule } from '../rule-schema'

const QUERY_LOGS_TOOL = 'query-logs'

function logsRule(rule: {
    id: string
    hasLogs: boolean
    requiresTool?: string[]
    suppressIfCalled?: string[]
    text: string
}): GuidanceRule {
    return emptyResultRule({
        id: rule.id,
        tool: QUERY_LOGS_TOOL,
        needsEventData: false,
        requiresTool: [QUERY_LOGS_TOOL, ...(rule.requiresTool ?? [])],
        suppressIfCalled: rule.suppressIfCalled,
        when: async ({ productState }) => (await productState.hasLogs()) === rule.hasLogs,
        text: rule.text,
    })
}

const rules: GuidanceRule[] = [
    logsRule({
        id: 'logs-empty-to-no-logs',
        hasLogs: false,
        requiresTool: ['docs-search'],
        suppressIfCalled: ['docs-search'],
        text: [
            'PostHog holds no logs for this project, in any service or date range.',
            'This result does not show whether a service tries to send logs.',
            'PostHog receives logs over OTLP, and `docs-search` finds the setup and troubleshooting steps.',
        ].join(' '),
    }),
    logsRule({
        id: 'logs-empty-to-no-match',
        hasLogs: true,
        text: 'This project has logs, but none matched this query in this date range.',
    }),
]

export default rules
