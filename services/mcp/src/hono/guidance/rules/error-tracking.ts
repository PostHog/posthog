import { emptyResultRule, hasArg } from '../empty-result-rule'
import type { GuidanceCall } from '../engine'
import type { GuidanceRule } from '../rule-schema'

export const MCP_GUIDANCE_ERROR_TRACKING_EMPTY_SETUP_FLAG = 'mcp-guidance-error-tracking-empty-setup'
export const MCP_GUIDANCE_ERROR_TRACKING_EMPTY_FILTERS_FLAG = 'mcp-guidance-error-tracking-empty-filters'
export const MCP_GUIDANCE_ERROR_TRACKING_EMPTY_RANGE_FLAG = 'mcp-guidance-error-tracking-empty-range'

const ERROR_TRACKING_ISSUES_LIST_TOOL = 'query-error-tracking-issues-list'

// `status` and `dateRange` are absent because the default query also sets them, and the range rule covers them.
const ERROR_TRACKING_NARROWING_FILTERS = [
    'searchQuery',
    'library',
    'release',
    'fingerprint',
    'url',
    'personId',
    'user',
    'filePath',
    'filterGroup',
    'assignee',
    'firstSeenAfter',
]

function errorTrackingFiltersIn(call: GuidanceCall): string[] {
    return ERROR_TRACKING_NARROWING_FILTERS.filter((filter) => hasArg(call, filter))
}

const rules: GuidanceRule[] = [
    emptyResultRule({
        id: 'error-tracking-empty-to-setup',
        flag: MCP_GUIDANCE_ERROR_TRACKING_EMPTY_SETUP_FLAG,
        tool: ERROR_TRACKING_ISSUES_LIST_TOOL,
        suppressIfCalled: ['docs-search'],
        requiresTool: ['docs-search'],
        when: async ({ productState }) => (await productState.hasErrorTrackingIssues()) === false,
        text: [
            'PostHog holds no error tracking issues for this project, with any filter or date range.',
            'This result does not show whether an SDK tries to capture exceptions.',
            '`docs-search` finds the setup and troubleshooting steps for an SDK.',
        ].join(' '),
    }),
    emptyResultRule({
        id: 'error-tracking-empty-to-filters',
        flag: MCP_GUIDANCE_ERROR_TRACKING_EMPTY_FILTERS_FLAG,
        tool: ERROR_TRACKING_ISSUES_LIST_TOOL,
        maxPerSession: 2,
        when: async ({ call, productState }) =>
            errorTrackingFiltersIn(call).length > 0 && (await productState.hasErrorTrackingIssues()) === true,
        text: (call) =>
            [
                'This project has error tracking issues, but none matched this query.',
                `This call filtered on ${errorTrackingFiltersIn(call)
                    .map((filter) => `\`${filter}\``)
                    .join(', ')}.`,
                'Remove or loosen these filters and try again before you report that no matching errors exist.',
            ].join(' '),
    }),
    emptyResultRule({
        id: 'error-tracking-empty-to-range',
        flag: MCP_GUIDANCE_ERROR_TRACKING_EMPTY_RANGE_FLAG,
        tool: ERROR_TRACKING_ISSUES_LIST_TOOL,
        when: async ({ call, productState }) =>
            errorTrackingFiltersIn(call).length === 0 && (await productState.hasErrorTrackingIssues()) === true,
        text: [
            'This project has error tracking issues, but none matched this status, date range and test account filter.',
            'This tool returns only issues seen during `dateRange`. `status` defaults to `active`, and `filterTestAccounts` defaults to true.',
            'Try a wider `dateRange`, `status: "all"` or `filterTestAccounts: false` before you report that no errors exist.',
        ].join(' '),
    }),
]

export default rules
