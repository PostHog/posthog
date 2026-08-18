import { LogMessage } from '~/queries/schema/schema-general'

import { LogExplanation } from './components/LogsViewer/LogDetailsModal/Tabs/ExploreWithAI/types'
import {
    logsExplainLogWithAICreate as generatedLogsExplainLogWithAICreate,
    logsQueryCreate as generatedLogsQueryCreate,
    logsSparklineCreate as generatedLogsSparklineCreate,
} from './generated/api'

export interface LogsQueryResponseAdapter {
    results: LogMessage[]
    hasMore?: boolean
    nextCursor?: string | null
    maxExportableLogs: number
    columns?: string[]
}

export const logsQueryCreate = generatedLogsQueryCreate as unknown as (
    projectId: string,
    request: { query: Record<string, any>; signal?: AbortSignal },
    options?: RequestInit
) => Promise<LogsQueryResponseAdapter>

export const logsSparklineCreate = generatedLogsSparklineCreate as unknown as (
    projectId: string,
    request: { query: Record<string, any>; signal?: AbortSignal },
    options?: RequestInit
) => Promise<Record<string, any>[]>

export const logsExplainLogWithAICreate = generatedLogsExplainLogWithAICreate as unknown as (
    projectId: string,
    request: { uuid: string; timestamp: string }
) => Promise<LogExplanation>
