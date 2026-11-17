import { emptyResultRule } from '../empty-result-rule'
import type { GuidanceRule } from '../rule-schema'

const NO_SPANS = [
    'PostHog holds no trace spans for this project, in any service or date range.',
    'This result does not show whether a service tries to send spans.',
    'PostHog receives spans from its Node.js and Python SDKs and over OTLP, and `docs-search` finds the setup and troubleshooting steps.',
].join(' ')

const NO_MATCH = {
    'query-apm-spans': 'This project has spans, but none matched this query in this date range.',
    'apm-services-list': 'This project has spans, but no service matched in this date range.',
}

const rules: GuidanceRule[] = Object.entries(NO_MATCH).flatMap(([tool, noMatch]) => {
    const name = { 'query-apm-spans': 'spans', 'apm-services-list': 'services' }[tool]
    return [
        emptyResultRule({
            id: `tracing-${name}-empty-to-no-spans`,
            tool,
            needsEventData: false,
            requiresTool: [tool, 'docs-search'],
            suppressIfCalled: ['docs-search'],
            when: async ({ productState }) => (await productState.hasSpans()) === false,
            text: NO_SPANS,
        }),
        emptyResultRule({
            id: `tracing-${name}-empty-to-no-match`,
            tool,
            needsEventData: false,
            when: async ({ productState }) => (await productState.hasSpans()) === true,
            text: noMatch,
        }),
    ]
})

export default rules
