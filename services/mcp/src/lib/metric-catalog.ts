import type { MetricCatalogContent } from '@/tools/types'

export const EMPTY_METRIC_CATALOG_SECTION =
    '#### Metric discovery (semantic layer)\n\nThis project has no saved metrics, so skip `metric-list`. Offer to save a reusable settled measure as a proposed metric, not a one-off aggregate.'

export type MetricCatalogMode = 'lookup' | 'empty'

export function resolveMetricCatalogMode(content: MetricCatalogContent | undefined): MetricCatalogMode {
    return content?.count === 0 ? 'empty' : 'lookup'
}

// Lookup values are the templates' original text, so a project on the lookup path gets an unchanged prompt.
const CATALOG_ROUTING_NOTE =
    'Bare "retention" and "customers" are catalog terms that may have several approved definitions. Consult the catalog and clarify materially different matches instead of routing directly to an insight query.'
const LOOKUP_ROUTING = [
    '"Count / rate / latency / cost of a named thing" -> `metric-list` first; run a matching governed metric before any insight query',
    '"How many / how much / over time / compare periods" -> `metric-list` first, then `query-trends` if no metric fits, approved or proposed',
    '"Conversion rate / drop-off / funnel / step completion" -> `metric-list` first, then `query-funnel` if no metric fits, approved or proposed',
    '"Do users come back / cohort retention / churn" -> `query-retention` after catalog routing',
].join('\n- ')
const EMPTY_ROUTING = [
    '"How many / how much / over time / compare periods" -> `query-trends`',
    '"Conversion rate / drop-off / funnel / step completion" -> `query-funnel`',
    '"Do users come back / cohort retention / churn" -> `query-retention`',
].join('\n- ')
const EXAMPLE_CATALOG_FIRST = 'Assistant: A weekly count is a governed shape, so the catalog comes first.'
const EXAMPLE_LIST_CALL = '[Runs posthog:exec({ "command": "call metric-list {\\"limit\\": 100}" })]'
const EXAMPLE_NO_MATCH =
    'Assistant: No metric covers weekly active users, approved or proposed, so I fall through to the query tools and confirm the schema.'
const EXAMPLE_LIST_CALL_CLAUDE = '[Runs `posthog:exec({"command":"call metric-list {\\"limit\\":100}"})`]'
const EXAMPLE_NO_MATCH_CLAUDE = 'Assistant: No metric fits, approved or proposed, so I fall through to the query tools.'
const METRIC_CHANGE_CATALOG_STEP =
    '1. Check the governed catalog for an onboarding conversion metric (the `metric-list` tool); run it with `data-catalog-metric-run` if one fits, with a warning if it is proposed or drifted, otherwise continue'
const METRIC_CHANGE_CATALOG_REASON =
    '1. A conversion rate is a governed shape, so the catalog is checked before any query.'

export function metricCatalogPromptVars(mode: MetricCatalogMode): Record<string, string> {
    if (mode === 'empty') {
        return {
            catalog_routing_note: '',
            metric_routing: EMPTY_ROUTING,
            metric_example_steps: '',
            metric_example_steps_claude: '',
            metric_change_catalog_step: '',
            metric_change_catalog_reason: '',
        }
    }
    return {
        catalog_routing_note: CATALOG_ROUTING_NOTE,
        metric_routing: LOOKUP_ROUTING,
        metric_example_steps: [EXAMPLE_CATALOG_FIRST, EXAMPLE_LIST_CALL, EXAMPLE_NO_MATCH].join('\n'),
        metric_example_steps_claude: [EXAMPLE_CATALOG_FIRST, EXAMPLE_LIST_CALL_CLAUDE, EXAMPLE_NO_MATCH_CLAUDE].join(
            '\n'
        ),
        metric_change_catalog_step: METRIC_CHANGE_CATALOG_STEP,
        metric_change_catalog_reason: METRIC_CHANGE_CATALOG_REASON,
    }
}
