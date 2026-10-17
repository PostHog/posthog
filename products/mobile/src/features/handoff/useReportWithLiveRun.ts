import { useQueryClient } from '@tanstack/react-query'
import { useFocusEffect } from 'expo-router'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { reportKeys } from '@/api/reports'
import type { TaskApi } from '@/api/tasks'
import { useProjectScope } from '@/auth/useProjectScope'

import { useDataMode } from '@/demo/demoMode'
import type { QueryState, ReportView } from '@/model/types'

import { useReport } from '../report/hooks'
import { useHandoffStore } from './handoffStore'
import { useHandoffEntry } from './hooks'
import { mergeLiveRun, runTarget } from './liveReport'
import type { RunStreamState } from './types'
import { useAppActive, useTaskRun } from './useTaskRun'

const STREAM_REFRESH_INTERVAL_MS = 2000

function refreshKey(state: RunStreamState | undefined): string {
    return state
        ? JSON.stringify([state.taskId, state.runId, state.status, state.turnEnded, state.prUrl, state.prUrls])
        : ''
}

// Lives outside `hooks.ts` because `report/hooks.ts` imports the hand-off actions from there.
export function useReportWithLiveRun(reportId: string): QueryState<ReportView> {
    const [focused, setFocused] = useState(false)
    useFocusEffect(
        useCallback(() => {
            setFocused(true)
            return () => setFocused(false)
        }, [])
    )
    const active = useAppActive() && focused
    const query = useReport(reportId, active, focused)
    const queryClient = useQueryClient()
    const scope = useProjectScope()
    const live = useDataMode() === 'live'
    const entry = useHandoffEntry(reportId)
    const report = query.data
    useEffect(() => {
        if (entry?.started && report && (report.work.assignee || report.task?.taskId === entry.started.taskId)) {
            useHandoffStore.getState().clearStarted(reportId)
        }
    }, [reportId, report, entry?.started])
    const target = live ? runTarget(report, entry) : undefined
    const taskId = target?.taskId
    const refresh = useCallback((): void => {
        if (!active || !scope) {
            return
        }
        void queryClient.invalidateQueries({ queryKey: reportKeys.detail(scope, reportId) })
        void queryClient.invalidateQueries({ queryKey: reportKeys.artefacts(scope, reportId) })
        if (taskId) {
            void queryClient.invalidateQueries({ queryKey: reportKeys.task(scope, taskId) })
        }
    }, [active, queryClient, scope, reportId, taskId])
    useEffect(() => {
        if (!live || !active) {
            return
        }
        let lastRefresh = 0
        let timer: ReturnType<typeof setTimeout> | undefined
        const flush = (): void => {
            timer = undefined
            lastRefresh = Date.now()
            refresh()
        }
        const unsubscribe = useHandoffStore.subscribe((next, previous) => {
            if (refreshKey(next.reports[reportId]?.live) === refreshKey(previous.reports[reportId]?.live)) {
                return
            }
            if (timer) {
                return
            }
            const delay = Math.max(0, STREAM_REFRESH_INTERVAL_MS - (Date.now() - lastRefresh))
            if (delay === 0) {
                flush()
            } else {
                timer = setTimeout(flush, delay)
            }
        })
        return () => {
            unsubscribe()
            if (timer) {
                clearTimeout(timer)
            }
        }
    }, [live, active, reportId, refresh])
    const cacheTaskSnapshot = useCallback(
        (task: TaskApi): void => {
            queryClient.setQueryData(reportKeys.task(scope, task.id), task)
        },
        [queryClient, scope]
    )
    useTaskRun(reportId, target, live && report !== undefined && active, refresh, cacheTaskSnapshot)
    const data = useMemo(() => (live && report ? mergeLiveRun(report, entry) : report), [live, report, entry])
    return data === report ? query : { ...query, data }
}
