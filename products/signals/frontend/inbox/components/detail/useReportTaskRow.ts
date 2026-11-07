import { combineUrl } from 'kea-router'
import { useCallback } from 'react'

import { urls } from 'scenes/urls'

import { isTerminalRunStatus } from 'products/posthog_ai/frontend/api/logics'
import { TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { captureInboxRunSummaryViewed } from '../../inboxAnalytics'
import type { ReportTaskEntry } from '../../logics/inboxReportDetailLogic'

export interface ReportTaskRowState {
    status: TaskRunStatus
    runId: string | null
    replayOnly: boolean
    summary: string | null
    taskUrl: string
    captureSummaryViewed: () => void
}

/** What a Runs row shows and links to, shared by `ReportTaskRow` and its quill sibling. */
export function useReportTaskRow(entry: ReportTaskEntry): ReportTaskRowState {
    const { task, purpose } = entry

    const status = task.latest_run?.status ?? TaskRunStatus.NOT_STARTED
    const runId = task.latest_run?.id ?? null
    const replayOnly = isTerminalRunStatus(task.latest_run?.status)
    const summary = task.latest_run?.task_summary?.trim() || null

    const captureSummaryViewed = useCallback(
        () => captureInboxRunSummaryViewed({ purpose, status, summaryLength: summary?.length ?? 0 }),
        [purpose, status, summary]
    )

    // Deep link to the run's own page in Tasks — the inline transcript is a preview, this is the
    // full surface (run history, composer). Falls back to the task when no run has started yet.
    const taskUrl = runId ? combineUrl(urls.taskDetail(task.id), { runId }).url : urls.taskDetail(task.id)

    return { status, runId, replayOnly, summary, taskUrl, captureSummaryViewed }
}
