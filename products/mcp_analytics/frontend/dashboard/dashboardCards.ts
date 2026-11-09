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
    | 'lab-scoreboard'
    | 'model-share-over-time'
    | 'lab-share-over-time'
    | 'protocol-version-share-over-time'
    | 'most-called-tools'
    | 'error-rate'
    | 'latency'
    | 'failure-reasons'
    | 'harness-error-rate'

// A Record so a new card id fails to compile until it has a label.
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
    'lab-scoreboard': 'AI lab scoreboard',
    'model-share-over-time': 'Model share of calls over time',
    'lab-share-over-time': 'AI lab share of calls over time',
    'protocol-version-share-over-time': 'Protocol version share of calls over time',
    'most-called-tools': 'Most called tools',
    'error-rate': 'Error rate',
    latency: 'Latency',
    'failure-reasons': 'Why calls fail',
    'harness-error-rate': 'Error rate by harness',
}

export interface McpDashboardCard {
    id: McpDashboardCardId
    label: string
}

export const MCP_CARD_IDS = Object.keys(CARD_LABELS) as McpDashboardCardId[]

const toCards = (ids: McpDashboardCardId[]): McpDashboardCard[] => ids.map((id) => ({ id, label: CARD_LABELS[id] }))

// Each list is one layout's Customize menu, in menu order. A card that appears in both layouts uses one id, so
// hiding it in one layout also hides it in the other.
export const MCP_DASHBOARD_CARDS = toCards([
    'kpis',
    'activity',
    'tool-usage',
    'harness',
    'model',
    'protocol-version',
    'tool-errors',
    'notable-sessions',
    'recent-activity',
])

export const MCP_LEADERBOARD_CARDS = toCards([
    'kpis',
    'activity',
    'lab-scoreboard',
    'model-share-over-time',
    'model',
    'lab-share-over-time',
    'harness',
    'protocol-version-share-over-time',
    'most-called-tools',
    'error-rate',
    'latency',
    'tool-errors',
    'failure-reasons',
    'harness-error-rate',
    'notable-sessions',
])
