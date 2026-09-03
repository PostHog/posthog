import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { urls } from 'scenes/urls'

import { OriginProduct } from 'products/posthog_ai/frontend/types/taskTypes'
import {
    ClaudeRuntimeAdapterEnumApi,
    ClaudeTaskRunCreateSchemaApi,
    ReasoningEffortEnumApi,
    RunSourceEnumApi,
    TaskExecutionModeEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

import { InboxReportActionType, captureInboxReportActionCompleted } from './inboxAnalytics'
import {
    SIGNAL_REPORT_TASK_DISCUSSION_RELATIONSHIP,
    SIGNAL_REPORT_TASK_IMPLEMENTATION_RELATIONSHIP,
    SignalReport,
    SignalReportTaskRelationship,
} from './types'
import { aiConsentDisabledReason } from './utils/aiConsent'
import { buildCreatePrReportPrompt, buildDiscussReportPrompt, isActionCapableReport } from './utils/kickoffPrompts'

// Cloud-adapted port of desktop `useDiscussReport` / `useCreatePrReport`. These are
// task-kickoff actions (create a cloud Task linked to the report, then navigate to it) –
// NOT a live chat surface. The created task carries the SignalReport linkage so the
// backend's agent pipeline can pick it up.

// The run endpoint rejects a model without its runtime adapter, so the two are always sent together.
type ClaudeRuntimeSelection = Pick<ClaudeTaskRunCreateSchemaApi, 'runtime_adapter' | 'model' | 'reasoning_effort'>

// Discuss is a focused exchange about a report (a question to answer, or a suggested next step to
// carry out) rather than a scheduled implementation run, so it pins the stronger model instead of
// taking the server-side default of Sonnet: the answer quality is what the user is here for, and
// the extra cost is bounded by the length of the conversation.
const DISCUSS_RUNTIME: ClaudeRuntimeSelection = {
    runtime_adapter: ClaudeRuntimeAdapterEnumApi.Claude,
    model: 'claude-opus-5',
    reasoning_effort: ReasoningEffortEnumApi.High,
}

// Pressing "Create PR" is a strong engagement signal — the user is committing to a real
// implementation run — so it pins the stronger model rather than taking the server-side default of
// Sonnet, giving the change the best shot at landing.
const CREATE_PR_RUNTIME: ClaudeRuntimeSelection = {
    runtime_adapter: ClaudeRuntimeAdapterEnumApi.Claude,
    model: 'claude-opus-5',
    reasoning_effort: ReasoningEffortEnumApi.High,
}

// The per-report cap 429 carries code `signal_report_task_cap` with its message under `error`
// (TaskRunErrorResponseSerializer); the per-user creation throttle is DRF's `throttled` 429 with
// `detail`. Both are user-facing copy the server owns. Matching on code, not status: other 429s
// (e.g. the compute-quota gate) are not task limits and belong on the generic failure path.
function taskLimitMessage(error: any): string | null {
    if (error?.code === 'signal_report_task_cap' || error?.code === 'throttled') {
        return error?.data?.error || error?.detail || 'Task limit reached for this report. Try again later.'
    }
    return null
}

// Shared error tail of both kickoff listeners: a recognized task-limit 429 gets the server's copy
// and a `limited` outcome; anything else is a plain failure.
function handleKickoffError(
    error: any,
    report: SignalReport,
    actionType: InboxReportActionType,
    fallbackMessage: string
): void {
    const limitMessage = taskLimitMessage(error)
    if (limitMessage) {
        lemonToast.error(limitMessage)
        captureInboxReportActionCompleted({
            report,
            actionType,
            outcome: 'limited',
            limitCode: error?.code ?? null,
        })
        return
    }
    lemonToast.error(error?.detail || error?.message || fallbackMessage)
    captureInboxReportActionCompleted({ report, actionType, outcome: 'failure' })
}

async function createReportTask(
    report: SignalReport,
    relationship: SignalReportTaskRelationship,
    prompt: string,
    fallbackTitle: string,
    runtimeSelection?: ClaudeRuntimeSelection
): Promise<void> {
    // `repository` is intentionally omitted: the backend resolves it for signal_report tasks.
    const task = await api.tasks.create({
        title: report.title?.trim() || fallbackTitle,
        description: prompt,
        origin_product: OriginProduct.SIGNAL_REPORT,
        // Linkage fields accepted by the tasks backend for the signal_report origin.
        signal_report: report.id,
        signal_report_task_relationship: relationship,
    } as Parameters<typeof api.tasks.create>[0])

    // Kick off a cloud run so the task actually executes — creating it alone lands the user on a
    // "This task hasn't been run yet" screen. `run_source` ties the run to the report and makes any
    // PR bot-authored server-side, mirroring the auto-start pipeline's `create_and_run_task`.
    const runOptions = {
        run_source: RunSourceEnumApi.SignalReport,
        signal_report_id: report.id,
        // Interactive, not the default background: the user lands on the run page right away, and the
        // agent-server only relays AskUserQuestion (and other approval prompts) to the client on
        // non-background runs — a background run's questions are parked and never rendered as a form.
        mode: TaskExecutionModeEnumApi.Interactive,
        // The agent-server self-delivers `pending_user_message` from run state on boot, and interactive
        // runs skip the workflow's forwarding path. Nothing falls back to the task description on the
        // ACP runtime, so without this the sandbox boots with no first turn and the run just idles.
        pending_user_message: prompt,
    }
    await api.tasks.run(task.id, runtimeSelection ? { ...runOptions, ...runtimeSelection } : runOptions)

    router.actions.push(urls.taskDetail(task.id))
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxTaskKickoffLogicValues {
    dataProcessingAccepted: boolean // aiConsentLogic
    dataProcessingApprovalDisabledReason: string | null // aiConsentLogic
    aiConsentDisabledReason: string | null
    isCreatingPr: boolean
    isDiscussing: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxTaskKickoffLogicActions {
    createPrFailure: () => {
        value: true
    }
    createPrFromReport: (
        report: SignalReport,
        feedback?: string
    ) => {
        feedback: string | undefined
        report: SignalReport
    }
    createPrSuccess: () => {
        value: true
    }
    discussReport: (
        report: SignalReport,
        reportUrl: string,
        question: string
    ) => {
        question: string
        report: SignalReport
        reportUrl: string
    }
    discussReportFailure: () => {
        value: true
    }
    discussReportSuccess: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxTaskKickoffLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        aiConsentDisabledReason: (
            dataProcessingAccepted: boolean,
            dataProcessingApprovalDisabledReason: string | null
        ) => string | null
    }
}

export type inboxTaskKickoffLogicType = MakeLogicType<
    inboxTaskKickoffLogicValues,
    inboxTaskKickoffLogicActions,
    Record<string, any>,
    inboxTaskKickoffLogicMeta
>

export const inboxTaskKickoffLogic = kea<inboxTaskKickoffLogicType>([
    path(['scenes', 'inbox', 'inboxTaskKickoffLogic']),

    connect({
        values: [aiConsentLogic, ['dataProcessingAccepted', 'dataProcessingApprovalDisabledReason']],
    }),

    actions({
        discussReport: (report: SignalReport, reportUrl: string, question: string) => ({ report, reportUrl, question }),
        createPrFromReport: (report: SignalReport, feedback?: string) => ({ report, feedback }),
        discussReportSuccess: true,
        discussReportFailure: true,
        createPrSuccess: true,
        createPrFailure: true,
    }),

    reducers({
        isDiscussing: [
            false,
            {
                discussReport: () => true,
                discussReportSuccess: () => false,
                discussReportFailure: () => false,
            },
        ],
        isCreatingPr: [
            false,
            {
                createPrFromReport: () => true,
                createPrSuccess: () => false,
                createPrFailure: () => false,
            },
        ],
    }),

    selectors({
        aiConsentDisabledReason: [
            (s) => [s.dataProcessingAccepted, s.dataProcessingApprovalDisabledReason],
            (dataProcessingAccepted: boolean, dataProcessingApprovalDisabledReason: string | null): string | null =>
                aiConsentDisabledReason(dataProcessingAccepted, dataProcessingApprovalDisabledReason),
        ],
    }),

    listeners(({ actions, values }) => ({
        discussReport: async ({ report, reportUrl, question }) => {
            // The CTAs carry this as a `disabledReason`, but Discuss also submits on Enter, and the
            // run endpoint enforces no consent of its own.
            if (values.aiConsentDisabledReason) {
                lemonToast.error(values.aiConsentDisabledReason)
                captureInboxReportActionCompleted({
                    report,
                    actionType: 'discuss',
                    outcome: 'blocked',
                    blockedReason: values.aiConsentDisabledReason,
                })
                actions.discussReportFailure()
                return
            }
            // The popover renders from a snapshot that can go stale between load and submit (the
            // report resolves, fails, or gets suppressed meanwhile), so the action-vs-answer framing
            // is derived from the report's current server-side state. A failed refetch fails closed:
            // `null` pins the run to answering.
            let currentReport: SignalReport | null = null
            try {
                currentReport = await api.signalReports.get(report.id)
            } catch {
                currentReport = null
            }
            // The pane can offer an action suggestion the fresh state no longer supports. The run
            // still goes out (the reader may still want the answer), but downgrading silently would
            // misrepresent what the click bought - so say so. Only when the state is confirmed
            // changed: a failed refetch also answers only, but "report changed" would be a guess.
            if (currentReport !== null && isActionCapableReport(report) && !isActionCapableReport(currentReport)) {
                lemonToast.info('This report can no longer take actions, so AI will answer instead.')
            }
            try {
                await createReportTask(
                    report,
                    SIGNAL_REPORT_TASK_DISCUSSION_RELATIONSHIP,
                    buildDiscussReportPrompt(currentReport, reportUrl, question),
                    'Ask AI about report',
                    DISCUSS_RUNTIME
                )
                captureInboxReportActionCompleted({ report, actionType: 'discuss', outcome: 'success' })
                actions.discussReportSuccess()
            } catch (error: any) {
                handleKickoffError(error, report, 'discuss', "Couldn't ask AI about this report. Try again.")
                actions.discussReportFailure()
            }
        },
        createPrFromReport: async ({ report, feedback }) => {
            if (values.aiConsentDisabledReason) {
                lemonToast.error(values.aiConsentDisabledReason)
                captureInboxReportActionCompleted({
                    report,
                    actionType: 'create_pr',
                    outcome: 'blocked',
                    blockedReason: values.aiConsentDisabledReason,
                })
                actions.createPrFailure()
                return
            }
            try {
                await createReportTask(
                    report,
                    SIGNAL_REPORT_TASK_IMPLEMENTATION_RELATIONSHIP,
                    buildCreatePrReportPrompt(report, feedback),
                    'Implement report fix',
                    CREATE_PR_RUNTIME
                )
                captureInboxReportActionCompleted({ report, actionType: 'create_pr', outcome: 'success' })
                actions.createPrSuccess()
            } catch (error: any) {
                handleKickoffError(error, report, 'create_pr', "Couldn't start the PR task. Try again.")
                actions.createPrFailure()
            }
        },
    })),
])
