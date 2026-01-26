import type { ToolBase, ZodObjectAny } from '@/tools/types'

import createInsight from './createInsight'
import executeSQL from './executeSQL'
import filterSessionRecordings from './filterSessionRecordings'
import searchErrorTrackingIssues from './searchErrorTrackingIssues'
import summarizeSessions from './summarizeSessions'
import upsertDashboard from './upsertDashboard'

// Map of PostHog AI tool names to tool factory functions
export const PHAI_TOOLS_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
    'phai-create-insight': createInsight,
    'phai-execute-sql': executeSQL,
    'phai-filter-session-recordings': filterSessionRecordings,
    'phai-search-error-tracking-issues': searchErrorTrackingIssues,
    'phai-summarize-sessions': summarizeSessions,
    'phai-upsert-dashboard': upsertDashboard,
}
