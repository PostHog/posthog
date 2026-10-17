import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef } from 'react'

import { NotSignedInError } from '@/api/client'
import { reportKeys, retryUnlessMissing } from '@/api/reports'
import { getTask, type TaskApi } from '@/api/tasks'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { useDemoReportQuery } from '@/demo/hooks'
import { toError } from '@/lib/errors'
import { type ReportTaskInput, reportTaskId, reportView } from '@/model/adapters/report'
import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'
import type { InboxItem, QueryState, ReportActions, ReportView } from '@/model/types'

import { useHandoffActions } from '../handoff/hooks'
import { buildReportImplementationPrompt } from '../handoff/prompt'
import { useAppActive } from '../handoff/useTaskRun'
import { type InboxQueryState, useSetReadAction } from '../inbox/hooks'
import { useSetPriorityAction } from '../priority/hooks'
import { useSetReviewersAction } from '../reviewers/hooks'
import { useSnoozeAction } from '../snooze/hooks'
import { useDismissAction, useResolveAction } from '../verdict/hooks'
import { reportArtefactsQuery, reportDetailQuery, reportPageQuery, reportSignalsQuery } from './queries'

export const REPORT_POLL_INTERVAL_MS = 15_000

/** `TaskSerializer` also returns who created the task, which names who handed the report off. */
type TaskWithCreator = TaskApi & Pick<ReportTaskInput, 'created_by'>

// The screen waits for the Today page to answer (a 404 means no Today), and for the signals only when there is no
// page, because they are the evidence then.
function useLiveReport(reportId: string, enabled: boolean, refreshWhileVisible: boolean): QueryState<ReportView> {
    const scope = useProjectScope()
    const appActive = useAppActive()
    const active = enabled && appActive && scope !== null
    const queryClient = useQueryClient()
    const refetchInterval = active && refreshWhileVisible ? REPORT_POLL_INTERVAL_MS : false
    const [report, artefacts, page, signals] = useQueries({
        queries: [
            { ...reportDetailQuery(scope, reportId), enabled: active, refetchInterval, refetchOnMount: 'always' },
            { ...reportArtefactsQuery(scope, reportId), enabled: active, refetchInterval, refetchOnMount: 'always' },
            { ...reportPageQuery(scope, reportId), enabled: active, refetchOnMount: 'always' },
            { ...reportSignalsQuery(scope, reportId), enabled: active, refetchOnMount: 'always' },
        ],
    })
    const taskId = report.data && artefacts.data ? reportTaskId(report.data, artefacts.data.results) : undefined
    const task = useQuery({
        queryKey: reportKeys.task(scope, taskId),
        queryFn: ({ signal }) => getTask(taskId as string, signal) as Promise<TaskWithCreator>,
        enabled: active && taskId !== undefined,
        retry: retryUnlessMissing,
        refetchInterval,
        // `useQuery` keeps its observer when Prev/Next changes `taskId`, so `refetchOnMount` cannot refresh the task.
        staleTime: 0,
    })

    const wasActive = useRef(active)
    useEffect(() => {
        if (active && !wasActive.current) {
            void queryClient.invalidateQueries({ queryKey: reportKeys.detail(scope, reportId) })
            void queryClient.invalidateQueries({ queryKey: reportKeys.artefacts(scope, reportId) })
            if (taskId) {
                void queryClient.invalidateQueries({ queryKey: reportKeys.task(scope, taskId) })
            }
        }
        wasActive.current = active
    }, [active, queryClient, scope, reportId, taskId])

    // Retrying missing evidence resets its status to pending, but must not hide an already loaded report.
    const pageSettled = page.isFetched
    const signalsNeeded = !page.data
    const signalsSettled = signals.isFetched
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
        const isRefetching =
            report.isFetching || artefacts.isFetching || page.isFetching || signals.isFetching || task.isFetching
        return successQuery(view, { refetch, isRefetching })
    }
    return { ...loadingQuery<ReportView>(), refetch }
}

export function useReport(reportId: string, refreshWhileVisible = false, enabled = true): QueryState<ReportView> {
    const mode = useDataMode()
    const demoQuery = useDemoReportQuery(reportId)
    const liveQuery = useLiveReport(reportId, mode === 'live' && enabled, refreshWhileVisible)
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
    const resolve = useResolveAction(reportId)
    const dismiss = useDismissAction(reportId)
    const reviewers = useSetReviewersAction(reportId)
    const priority = useSetPriorityAction(reportId)
    const markRead = useSetReadAction(reportId, true)
    const markUnread = useSetReadAction(reportId, false)
    return {
        handOff: handoff.handOff.run,
        answerDecision: handoff.answerDecision.run,
        undoDecision: handoff.undoDecision.run,
        snooze: snooze.run,
        resolve: resolve.run,
        dismiss: dismiss.run,
        setReviewers: reviewers.run,
        setPriority: priority.run,
        markRead: markRead.run,
        markUnread: markUnread.run,
        pending: {
            handOff: handoff.handOff.pending,
            answer: handoff.answerDecision.pending || handoff.undoDecision.pending,
            snooze: snooze.pending,
            reviewers: reviewers.pending,
            priority: priority.pending,
            resolve: resolve.pending,
            dismiss: dismiss.pending,
        },
    }
}

export interface ReportNeighbors {
    previousId?: string
    nextId?: string
}

// While the server has more pages, the loaded rows are not the whole list, so Prev and Next stop at its ends.
export function reportNeighbors(items: InboxItem[] | undefined, reportId: string, hasMore = false): ReportNeighbors {
    if (!items || items.length < 2) {
        return {}
    }
    const last = items.length - 1
    const index = items.findIndex((item) => item.reportId === reportId)
    if (index === -1) {
        return { previousId: hasMore ? undefined : items[last]?.reportId, nextId: items[0]?.reportId }
    }
    const previous = index > 0 ? items[index - 1] : hasMore ? undefined : items[last]
    const next = index < last ? items[index + 1] : hasMore ? undefined : items[0]
    return { previousId: previous?.reportId, nextId: next?.reportId }
}

/** Prev and Next in inbox order. On the last loaded report, it loads the next page so Next can go on. */
export function useReportNeighbors(inbox: InboxQueryState, reportId: string): ReportNeighbors {
    const { data, hasMore, loadMore } = inbox
    const atLoadedEnd = hasMore && data !== undefined && data[data.length - 1]?.reportId === reportId
    useEffect(() => {
        if (atLoadedEnd) {
            loadMore()
        }
    }, [atLoadedEnd, loadMore])
    return useMemo(() => reportNeighbors(data, reportId, hasMore), [data, reportId, hasMore])
}
