import { useQueries, useQuery } from '@tanstack/react-query'
import { useCallback, useMemo } from 'react'

import { NotSignedInError } from '@/api/client'
import { fetchReport, fetchReportArtefacts, fetchReportSignals, reportKeys, retryUnlessMissing } from '@/api/reports'
import { getTask, type TaskApi } from '@/api/tasks'
import { fetchReportPage } from '@/api/today'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { useDemoReportQuery } from '@/demo/hooks'
import { toError } from '@/lib/errors'
import { type ReportTaskInput, reportTaskId, reportView } from '@/model/adapters/report'
import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'
import type { InboxItem, QueryState, ReportActions, ReportView } from '@/model/types'

import { useHandoffActions } from '../handoff/hooks'
import { buildReportImplementationPrompt } from '../handoff/prompt'
import { useMarkReadAction } from '../inbox/hooks'
import { useSetReviewersAction } from '../reviewers/hooks'
import { useSnoozeAction } from '../snooze/hooks'

/** `TaskSerializer` also returns who created the task, which names who handed the report off. */
type TaskWithCreator = TaskApi & Pick<ReportTaskInput, 'created_by'>

// The screen waits for the Today page to answer (a 404 means no Today), and for the signals only when there is no
// page, because they are the evidence then.
function useLiveReport(reportId: string, enabled: boolean): QueryState<ReportView> {
    const scope = useProjectScope()
    const active = enabled && scope !== null
    const [report, artefacts, page, signals] = useQueries({
        queries: [
            {
                queryKey: reportKeys.detail(scope, reportId),
                queryFn: ({ signal }: { signal: AbortSignal }) => fetchReport(reportId, signal),
                enabled: active,
            },
            {
                queryKey: reportKeys.artefacts(scope, reportId),
                queryFn: ({ signal }: { signal: AbortSignal }) => fetchReportArtefacts(reportId, signal),
                enabled: active,
            },
            {
                queryKey: reportKeys.page(scope, reportId),
                queryFn: ({ signal }: { signal: AbortSignal }) => fetchReportPage(reportId, signal),
                enabled: active,
                retry: retryUnlessMissing,
            },
            {
                queryKey: reportKeys.signals(scope, reportId),
                queryFn: ({ signal }: { signal: AbortSignal }) => fetchReportSignals(reportId, signal),
                enabled: active,
            },
        ],
    })
    const taskId = report.data && artefacts.data ? reportTaskId(report.data, artefacts.data.results) : undefined
    const task = useQuery({
        queryKey: reportKeys.task(scope, taskId),
        queryFn: ({ signal }) => getTask(taskId as string, signal) as Promise<TaskWithCreator>,
        enabled: active && taskId !== undefined,
        retry: retryUnlessMissing,
    })

    const pageSettled = page.isSuccess || page.isError
    const signalsNeeded = !page.data
    const signalsSettled = signals.isSuccess || signals.isError
    const ready =
        report.data !== undefined && artefacts.data !== undefined && pageSettled && (!signalsNeeded || signalsSettled)

    const view = useMemo((): ReportView | undefined => {
        if (!ready || !scope || !report.data || !artefacts.data) {
            return undefined
        }
        const adapted = reportView({
            report: report.data,
            artefacts: artefacts.data.results,
            signals: signals.data?.signals,
            page: page.data,
            task: task.data,
            host: scope.host,
            projectId: scope.projectId,
        })
        return { ...adapted, prompt: buildReportImplementationPrompt(adapted, adapted.webUrl) }
    }, [ready, scope, report.data, artefacts.data, signals.data, page.data, task.data])

    const { refetch: refetchReport } = report
    const { refetch: refetchArtefacts } = artefacts
    const { refetch: refetchPage } = page
    const { refetch: refetchSignals } = signals
    const { refetch: refetchTask } = task
    const refetch = useCallback(
        () =>
            Promise.all([
                refetchReport(),
                refetchArtefacts(),
                refetchPage(),
                refetchSignals(),
                taskId ? refetchTask() : Promise.resolve(),
            ]),
        [refetchReport, refetchArtefacts, refetchPage, refetchSignals, refetchTask, taskId]
    )

    if (!scope) {
        return errorQuery(new NotSignedInError())
    }
    // A failed background refetch keeps the cached report on screen; only a first load that fails is an error.
    const failed = (report.data ? null : report.error) ?? (artefacts.data ? null : artefacts.error)
    if (failed) {
        return errorQuery(toError(failed), refetch)
    }
    if (view) {
        return successQuery(view, { refetch })
    }
    return { ...loadingQuery<ReportView>(), refetch }
}

export function useReport(reportId: string): QueryState<ReportView> {
    const mode = useDataMode()
    const demoQuery = useDemoReportQuery(reportId)
    const liveQuery = useLiveReport(reportId, mode === 'live')
    if (mode === 'loading') {
        return loadingQuery()
    }
    if (mode === 'demo') {
        return demoQuery
    }
    return liveQuery
}

export function useReportActions(reportId: string): ReportActions {
    const handoff = useHandoffActions(reportId)
    const snooze = useSnoozeAction(reportId)
    const reviewers = useSetReviewersAction(reportId)
    const markRead = useMarkReadAction(reportId)
    return {
        handOff: handoff.handOff.run,
        answerDecision: handoff.answerDecision.run,
        undoDecision: handoff.undoDecision.run,
        snooze: snooze.run,
        setReviewers: reviewers.run,
        markRead: markRead.run,
        pending: {
            handOff: handoff.handOff.pending,
            answer: handoff.answerDecision.pending || handoff.undoDecision.pending,
            snooze: snooze.pending,
            reviewers: reviewers.pending,
        },
    }
}

export interface ReportNeighbors {
    previousId?: string
    nextId?: string
}

export function reportNeighbors(items: InboxItem[] | undefined, reportId: string): ReportNeighbors {
    if (!items || items.length < 2) {
        return {}
    }
    const index = items.findIndex((item) => item.reportId === reportId)
    if (index === -1) {
        return { previousId: items[items.length - 1]?.reportId, nextId: items[0]?.reportId }
    }
    const previous = items[(index - 1 + items.length) % items.length]
    const next = items[(index + 1) % items.length]
    return { previousId: previous?.reportId, nextId: next?.reportId }
}

export function useReportNeighbors(items: InboxItem[] | undefined, reportId: string): ReportNeighbors {
    return useMemo(() => reportNeighbors(items, reportId), [items, reportId])
}
