import { create } from 'zustand'

import type { TaskRunApi } from '@/api/tasks'
import { addSessionEndTask } from '@/auth/authStore'
import type { DecisionQuestion } from '@/model/types'
import { requestKind } from './permissionRequest'
import {
    applyRunSnapshot,
    type FrameContext,
    initialRunState,
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
    live?: RunStreamState
    partial?: { requestId: string; labels: string[] }
    answer?: StoredAnswer
    notice?: string
    refresh: number
}

interface HandoffStoreState {
    reports: Record<string, ReportHandoff>
    setStarted: (reportId: string, started: { taskId: string; runId: string }) => void
    applySnapshot: (reportId: string, taskId: string, run: TaskRunApi) => RunStreamState
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
        setStarted: (reportId, started) =>
            update(reportId, (entry) => ({
                ...entry,
                started,
                notice: undefined,
                answer: undefined,
                partial: undefined,
            })),
        applySnapshot: (reportId, taskId, run) => {
            const current = get().reports[reportId]?.live
            const base = current && current.runId === run.id ? current : initialRunState(taskId, run.id, run.status)
            const live = applyRunSnapshot(base, run)
            update(reportId, (entry) => ({ ...entry, live }))
            return live
        },
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
