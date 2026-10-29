import { useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useStoreWithEqualityFn } from 'zustand/traditional'

import { reportKeys } from '@/api/reports'
import { useProjectScope } from '@/auth/useProjectScope'
import { demoDecisionMeta } from '@/demo/briefings'
import { useDemoMode } from '@/demo/demoMode'
import { useAiApproval } from '@/features/ai/aiApproval'
import { track } from '@/lib/analytics'
import { type AsyncAction, useAsyncAction } from '@/lib/useAsyncAction'
import type { DecisionAnswerInput, DecisionQuestion } from '@/model/types'

import { CommandFailedError, type DeliveryOutcome, deliverPermissionResponse } from './commands'
import { handoffEntry, type ReportHandoff, type StoredAnswer, useHandoffStore } from './handoffStore'
import { handoffErrorMessage, handoffFailureReason, kickOffReportTask } from './kickoff'
import { currentDecision, sameVisibleEntry, visibleAnswer } from './liveReport'
import { planAnswer } from './permissionRequest'
import { buildHandoffRunRequest } from './runOptions'
import { useRunOptionsStore } from './runOptionsStore'
import type { HandoffAnswer, PendingRequestKind } from './types'
import { fetchRunDefaults } from './useRunOptions'

const deliveries = new Map<string, AbortController>()

export function useHandoffEntry(reportId: string): ReportHandoff | undefined {
    return useStoreWithEqualityFn(useHandoffStore, (state) => state.reports[reportId], sameVisibleEntry)
}

export function useHandoffNotice(reportId: string): string | undefined {
    const demo = useDemoMode((state) => state.enabled)
    const notice = useHandoffStore((state) => state.reports[reportId]?.notice)
    return demo ? undefined : notice
}

export function useDecisionAnswer(reportId: string): HandoffAnswer | undefined {
    const demo = useDemoMode((state) => state.enabled)
    const demoAnswer = useDemoMode((state) => state.decisions[reportId])
    const entry = useHandoffEntry(reportId)
    return useMemo(() => {
        if (demo) {
            return demoAnswer ? { ...demoAnswer, canUndo: true } : undefined
        }
        const answer = visibleAnswer(entry, currentDecision(entry))
        if (!answer) {
            return undefined
        }
        return {
            questionId: answer.questionId,
            text: answer.text,
            ...(answer.optionId ? { optionId: answer.optionId } : {}),
            canUndo: false,
        }
    }, [demo, demoAnswer, entry])
}

export interface HandoffActions {
    handOff: AsyncAction<[]>
    answerDecision: AsyncAction<[DecisionAnswerInput]>
    undoDecision: AsyncAction<[]>
}

export function answerErrorMessage(error: unknown): string {
    if (error instanceof CommandFailedError) {
        return "PostHog didn't accept your answer. Try again."
    }
    return "Couldn't send your answer. Try again."
}

type Delivery = (signal: AbortSignal) => Promise<DeliveryOutcome>

export function useHandoffActions(reportId: string): HandoffActions {
    const demo = useDemoMode((state) => state.enabled)
    const demoHandOff = useDemoMode((state) => state.handOff)
    const demoAnswer = useDemoMode((state) => state.answer)
    const demoUndo = useDemoMode((state) => state.undoAnswer)
    const queryClient = useQueryClient()
    const scope = useProjectScope()
    const approval = useAiApproval('handoff', reportId)

    const refreshReport = (): void => {
        void queryClient.invalidateQueries({ queryKey: reportKeys.report(scope, reportId) })
        void queryClient.invalidateQueries({ queryKey: reportKeys.inbox(scope) })
    }

    // Aborting delivery stops local work; it cannot retract an answer accepted by the server.
    const deliverAnswer = async (
        question: DecisionQuestion,
        input: DecisionAnswerInput,
        target: { requestId: string; kind: PendingRequestKind },
        send: Delivery
    ): Promise<void> => {
        const { requestId } = target
        const store = useHandoffStore.getState()
        const originatingRun = handoffEntry(reportId).live
        if (!originatingRun || approval.signal.aborted) {
            return
        }
        const isCurrentRun = (): boolean => {
            const current = handoffEntry(reportId).live
            return (
                current?.taskId === originatingRun.taskId &&
                current.runId === originatingRun.runId &&
                (!current.pending || current.pending.record.requestId === requestId)
            )
        }
        const controller = new AbortController()
        const abort = (): void => controller.abort()
        approval.signal.addEventListener('abort', abort, { once: true })
        deliveries.get(reportId)?.abort()
        deliveries.set(reportId, controller)
        const answer: StoredAnswer = {
            questionId: question.id,
            question,
            ...(input.optionId ? { optionId: input.optionId } : {}),
            text: input.text,
            delivery: 'sending',
            activity: handoffEntry(reportId).live?.activity ?? 0,
        }
        store.setNotice(reportId, undefined)
        store.setAnswer(reportId, answer)
        try {
            const outcome = await send(controller.signal)
            if (controller.signal.aborted || !isCurrentRun()) {
                return
            }
            store.markHandled(reportId, requestId)
            if (outcome === 'resolved') {
                const activity = handoffEntry(reportId).live?.activity ?? answer.activity
                store.setAnswer(reportId, { ...answer, delivery: 'delivered', activity })
                store.setPartial(reportId, undefined)
                track('mobile_decision_answered', {
                    report_id: reportId,
                    kind: target.kind,
                    picked_option: Boolean(input.optionId),
                })
                return
            }
            store.setAnswer(reportId, undefined)
            store.setPartial(reportId, undefined)
            store.setNotice(
                reportId,
                outcome === 'ended'
                    ? "This run has ended, so your answer wasn't sent. Open the chat to continue."
                    : 'PostHog already moved on from this question.'
            )
            store.requestRefresh(reportId)
            refreshReport()
        } catch (error) {
            if (controller.signal.aborted || !isCurrentRun()) {
                return
            }
            store.setAnswer(reportId, undefined)
            store.setNotice(reportId, answerErrorMessage(error))
        } finally {
            approval.signal.removeEventListener('abort', abort)
            if (deliveries.get(reportId) === controller) {
                deliveries.delete(reportId)
            }
        }
    }

    // Hand-off and answer failures show in the action bar, so these actions resolve instead of
    // rejecting: every caller fires them without awaiting the result.
    const handOff = useAsyncAction(async () => {
        if (demo) {
            demoHandOff(reportId)
            useRunOptionsStore.getState().reset()
            return
        }
        if (!(await approval.request())) {
            return
        }
        const store = useHandoffStore.getState()
        store.setNotice(reportId, undefined)
        try {
            const options = useRunOptionsStore.getState().options
            const run = buildHandoffRunRequest(options, await fetchRunDefaults(queryClient, scope))
            if (approval.signal.aborted) {
                return
            }
            const started = await kickOffReportTask(reportId, {
                run,
                signal: approval.signal,
                taskId: handoffEntry(reportId).unstartedTaskId,
                onTaskCreated: (taskId) => useHandoffStore.getState().setUnstartedTask(reportId, taskId),
            })
            useHandoffStore.getState().setStarted(reportId, started)
            useRunOptionsStore.getState().reset()
            track('mobile_report_handed_off', {
                report_id: reportId,
                task_id: started.taskId,
                run_id: started.runId,
                model: options.model === 'default' ? 'default' : options.model.model,
                reasoning_effort: options.model === 'default' ? undefined : options.model.reasoningEffort,
                permission_mode: run.initial_permission_mode,
                has_branch: Boolean(run.branch),
            })
            refreshReport()
        } catch (error) {
            useHandoffStore.getState().setNotice(reportId, handoffErrorMessage(error))
            track('mobile_handoff_failed', {
                report_id: reportId,
                agent: 'posthog',
                reason: handoffFailureReason(error),
            })
        }
    })

    const answerDecision = useAsyncAction(async (input: DecisionAnswerInput) => {
        if (demo) {
            demoAnswer(reportId, { ...input, meta: demoDecisionMeta(input.text) })
            return
        }
        const entry = handoffEntry(reportId)
        const live = entry.live
        const question = currentDecision(entry)
        if (!live || !question || question.id !== input.questionId) {
            // The card the user answered is gone; fetch the run so the screen catches up.
            useHandoffStore.getState().requestRefresh(reportId)
            return
        }
        const run = { taskId: live.taskId, runId: live.runId }
        if (live.pending) {
            const requestId = live.pending.record.requestId
            const answered = entry.partial?.requestId === requestId ? entry.partial.labels : []
            const plan = planAnswer(live.pending, answered, input)
            if (plan.type === 'next_question') {
                useHandoffStore.getState().setPartial(reportId, { requestId, labels: [...answered, plan.label] })
                return
            }
            if (!(await approval.request())) {
                return
            }
            const current = handoffEntry(reportId)
            if (
                approval.signal.aborted ||
                current.live?.taskId !== run.taskId ||
                current.live.runId !== run.runId ||
                current.live.pending?.record.requestId !== requestId ||
                currentDecision(current)?.id !== question.id
            ) {
                return
            }
            await deliverAnswer(question, input, { requestId, kind: live.pending.kind }, (signal) =>
                deliverPermissionResponse(run, plan.params, { signal })
            )
            return
        }
    })

    const undoDecision = useAsyncAction(async () => {
        if (demo) {
            demoUndo(reportId)
            return
        }
    })

    return { handOff, answerDecision, undoDecision }
}
