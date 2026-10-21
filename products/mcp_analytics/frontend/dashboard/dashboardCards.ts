import { FEATURE_FLAGS, type FeatureFlagKey } from 'lib/constants'

export type McpDashboardCardId =
    | 'kpis'
    | 'intent-topics'
    | 'activity'
    | 'tool-usage'
    | 'harness'
    | 'model'
    | 'protocol-version'
    | 'tool-errors'
    | 'notable-sessions'
    | 'recent-activity'

// A Record so a new card id fails to compile until it has a label. Key order is menu order.
const CARD_LABELS: Record<McpDashboardCardId, string> = {
    kpis: 'Key metrics',
    'intent-topics': 'What agents use your server for',
    activity: 'Tool calls and errors',
    'tool-usage': 'Tool call breakdown',
    harness: 'Share of calls by harness',
    model: 'Share of calls by model',
    'protocol-version': 'Calls by MCP protocol version',
    'tool-errors': 'Tools with the highest error rate',
    'notable-sessions': 'Sessions flagged for review',
    'recent-activity': 'Recent activity',
}

export const MCP_DASHBOARD_CARDS = (Object.keys(CARD_LABELS) as McpDashboardCardId[]).map((id) => ({
    id,
    label: CARD_LABELS[id],
}))

// Cards that ship behind a flag stay out of the dashboard and the Customize menu until it is on.
export const MCP_DASHBOARD_CARD_FLAGS: Partial<Record<McpDashboardCardId, FeatureFlagKey>> = {
    'intent-topics': FEATURE_FLAGS.MCP_ANALYTICS_INTENT_TOPICS,
}
