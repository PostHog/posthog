export type McpDashboardCardId =
    | 'kpis'
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
