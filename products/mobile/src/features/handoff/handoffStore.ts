import { create } from 'zustand'

import type { TaskRunApi } from '@/api/tasks'
import { addSessionEndTask } from '@/auth/authStore'
import type { DecisionQuestion } from '@/model/types'
import { requestKind } from './permissionRequest'
import {
    applyRunSnapshot,
    type FrameContext,
    initialRunState,
    isTerminalRunStatus,
    markRequestHandled,
    type RunEffect,
    reduceFrame,
} from './runStream'
import type { AnswerDelivery, PermissionRecord, RunStreamState } from './types'

export interface StoredAnswer {
    questionId: string
    /** The card the answer was given on, so the decided card can stay after the agent clears it. */
    question: DecisionQuestion
    optionId?: string
    text: string
    delivery: AnswerDelivery
    /** `RunStreamState.activity` when the answer was delivered. A change means the run moved on. */
    activity: number
}

export interface ReportHandoff {
    started?: { taskId: string; runId: string }
    unstartedTaskId?: string
    live?: RunStreamState
    partial?: { requestId: string; labels: string[] }
    answer?: StoredAnswer
    notice?: string
    refresh: number
}

interface HandoffStoreState {
    reports: Record<string, ReportHandoff>
    setStarted: (reportId: string, started: { taskId: string; runId: string }) => void
    setUnstartedTask: (reportId: string, taskId: string) => void
    applySnapshot: (reportId: string, taskId: string, run: TaskRunApi) => RunStreamState
    clearStarted: (reportId: string) => void
    publishHydration: (
        reportId: string,
        state: RunStreamState,
        answerAtStart?: StoredAnswer
    ) => RunStreamState | undefined
    beginFollow: (reportId: string, taskId: string, runId: string) => void
    settleStreamEnd: (reportId: string, runId: string) => void
    setConnection: (reportId: string, runId: string, connection: RunStreamState['connection']) => void
    applyFrame: (reportId: string, runId: string, frame: unknown, context: FrameContext) => RunEffect[]
    markHandled: (reportId: string, requestId: string) => void
    surfaceRequest: (reportId: string, record: PermissionRecord) => void
    endTurnLocally: (reportId: string) => void
    setPartial: (reportId: string, partial: ReportHandoff['partial']) => void
    setAnswer: (reportId: string, answer: StoredAnswer | undefined) => void
    setNotice: (reportId: string, notice: string | undefined) => void
    requestRefresh: (reportId: string) => void
}

const EMPTY: ReportHandoff = { refresh: 0 }

export const useHandoffStore = create<HandoffStoreState>()((set, get) => {
    const update = (reportId: string, change: (entry: ReportHandoff) => ReportHandoff): void =>
        set((state) => ({ reports: { ...state.reports, [reportId]: change(state.reports[reportId] ?? EMPTY) } }))

    const updateLive = (reportId: string, change: (live: RunStreamState) => RunStreamState): void =>
        update(reportId, (entry) => (entry.live ? { ...entry, live: change(entry.live) } : entry))

    return {
        reports: {},
        setUnstartedTask: (reportId, unstartedTaskId) => update(reportId, (entry) => ({ ...entry, unstartedTaskId })),
        setStarted: (reportId, started) =>
            update(reportId, (entry) => ({
                ...entry,
                started,
                unstartedTaskId: undefined,
                notice: undefined,
                answer: undefined,
                partial: undefined,
            })),
        applySnapshot: (reportId, taskId, run) => {
            const current = get().reports[reportId]?.live
            const base =
                current && current.taskId === taskId && current.runId === run.id
                    ? current
                    : initialRunState(taskId, run.id, run.status)
            const live = applyRunSnapshot(base, run)
            update(reportId, (entry) => ({
                ...entry,
                ...(current?.taskId === taskId && current.runId === run.id
                    ? {}
                    : { answer: undefined, partial: undefined, notice: undefined }),
                live,
            }))
            return live
        },
        clearStarted: (reportId) => update(reportId, (entry) => ({ ...entry, started: undefined })),
        publishHydration: (reportId, hydrated, answerAtStart) => {
            const current = get().reports[reportId]?.live
            if (!current || current.taskId !== hydrated.taskId || current.runId !== hydrated.runId) {
                return undefined
            }
            const handledRequestIds = [...new Set([...hydrated.handledRequestIds, ...current.handledRequestIds])]
            const prUrls = [...new Set([...current.prUrls, ...hydrated.prUrls])]
            const live = isTerminalRunStatus(current.status)
                ? { ...current, prUrls, prUrl: current.prUrl ?? hydrated.prUrl }
                : {
                      ...hydrated,
                      connection: 'connected' as const,
                      prUrls,
                      handledRequestIds,
                      pending:
                          hydrated.pending && !handledRequestIds.includes(hydrated.pending.record.requestId)
                              ? hydrated.pending
                              : undefined,
                  }
            update(reportId, (entry) => ({
                ...entry,
                live,
                answer:
                    entry.answer && entry.answer !== answerAtStart
                        ? { ...entry.answer, activity: live.activity }
                        : entry.answer,
            }))
            return live
        },
        beginFollow: (reportId, taskId, runId) =>
            update(reportId, (entry) => ({
                ...entry,
                ...(entry.live?.taskId === taskId && entry.live.runId === runId
                    ? {}
                    : { answer: undefined, partial: undefined, notice: undefined }),
                live:
                    entry.live?.taskId === taskId && entry.live.runId === runId
                        ? entry.live
                        : initialRunState(taskId, runId, 'not_started'),
            })),
        settleStreamEnd: (reportId, runId) =>
            updateLive(reportId, (live) =>
                live.runId === runId
                    ? { ...live, connection: undefined, phase: live.turnEnded ? 'idle' : 'unknown' }
                    : live
            ),
        setConnection: (reportId, runId, connection) =>
            updateLive(reportId, (live) => (live.runId === runId ? { ...live, connection } : live)),
        applyFrame: (reportId, runId, frame, context) => {
            const current = get().reports[reportId]?.live
            if (!current || current.runId !== runId) {
                return []
            }
            const result = reduceFrame(current, frame, context)
            if (result.state !== current) {
                update(reportId, (entry) => ({ ...entry, live: result.state }))
            }
            return result.effects
        },
        markHandled: (reportId, requestId) => updateLive(reportId, (live) => markRequestHandled(live, requestId)),
        surfaceRequest: (reportId, record) =>
            updateLive(reportId, (live) => ({
                ...live,
                handledRequestIds: live.handledRequestIds.filter((id) => id !== record.requestId),
                pending: { record, kind: requestKind(record), replayed: false },
            })),
        endTurnLocally: (reportId) => updateLive(reportId, (live) => ({ ...live, turnEnded: false })),
        setPartial: (reportId, partial) => update(reportId, (entry) => ({ ...entry, partial })),
        setAnswer: (reportId, answer) => update(reportId, (entry) => ({ ...entry, answer })),
        setNotice: (reportId, notice) => update(reportId, (entry) => ({ ...entry, notice })),
        requestRefresh: (reportId) => update(reportId, (entry) => ({ ...entry, refresh: entry.refresh + 1 })),
    }
})

// Hand-off state names the signed-in user's tasks and answers.
addSessionEndTask(() => useHandoffStore.setState({ reports: {} }))

export function handoffEntry(reportId: string): ReportHandoff {
    return useHandoffStore.getState().reports[reportId] ?? EMPTY
}
