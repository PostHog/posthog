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

export const MCP_DASHBOARD_CARDS: { id: McpDashboardCardId; label: string }[] = [
    { id: 'kpis', label: 'Key metrics' },
    { id: 'activity', label: 'Tool calls and errors' },
    { id: 'tool-usage', label: 'Tool call breakdown' },
    { id: 'harness', label: 'Share of calls by harness' },
    { id: 'model', label: 'Share of calls by model' },
    { id: 'protocol-version', label: 'Calls by MCP protocol version' },
    { id: 'tool-errors', label: 'Tools with the highest error rate' },
    { id: 'notable-sessions', label: 'Sessions flagged for review' },
    { id: 'recent-activity', label: 'Recent activity' },
]
