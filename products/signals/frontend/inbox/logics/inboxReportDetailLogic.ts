import {
    MakeLogicType,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SignalNode } from 'scenes/debug/signals/types'
import { personalIntegrationsLogic } from 'scenes/settings/user/personalIntegrationsLogic'
import type { PersonalGitHubIntegration } from 'scenes/settings/user/personalIntegrationsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { Task, TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'
import {
    signalsReportArtefactsDiff,
    signalsReportPrChecks,
    signalsReportPrComments,
    signalsReportPrReviewCommentDestroy,
    signalsReportPrReviewCommentReactionDestroy,
    signalsReportPrReviewCommentReactionsCreate,
    signalsReportPrReviewCommentsCreate,
    signalsReportPrReviewCommentUpdate,
    signalsReportsFeedbackCreate,
    signalsReportsSignalsRetrieve,
} from 'products/signals/frontend/generated/api'
import type {
    CommitDiffResponseApi,
    PullRequestCheckApi,
    PullRequestCommentApi,
    PullRequestCommentReactionApi,
    ReportChartApi,
} from 'products/signals/frontend/generated/api.schemas'
import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import {
    deriveTaskPurpose,
    PURPOSE_ORDER,
    ReportTaskPurpose,
    TaskRunArtefactContent,
} from '../components/detail/artefactTypes'
import {
    AvailableReviewerOption,
    buildAddReviewerOptions,
    CurrentReviewerUser,
} from '../components/detail/reviewerDisplay'
import {
    captureInboxReportFeedback,
    captureInboxReportFeedbackNote,
    InboxReportFeedbackSentiment,
} from '../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../inboxTaskKickoffLogic'
import {
    EnrichedReviewer,
    SignalReport,
    SignalReportArtefact,
    SignalReportArtefactResponse,
    SignalReportStatus,
} from '../types'
import { ChartPlacements, resolveChartPlacements } from '../utils/chartPlacement'

/** Run statuses that count as terminal. Mirrors desktop `isTerminalStatus` / `ReportTasksSection`. */
const TERMINAL_RUN_STATUSES: TaskRunStatus[] = [TaskRunStatus.COMPLETED, TaskRunStatus.FAILED, TaskRunStatus.CANCELLED]

// A report funds one implementation task at a time, enforced server-side by
// `_live_implementation_exists` in products/signals/backend/task_run_artefacts.py. Only a failed or
// cancelled run hands the slot back there, so `completed` is deliberately absent: reusing
// TERMINAL_RUN_STATUSES here would offer a second PR the server then refuses.
const IMPLEMENTATION_SLOT_RELEASING_STATUSES: TaskRunStatus[] = [TaskRunStatus.FAILED, TaskRunStatus.CANCELLED]

// The task↔report association is the `task_run` artefact log now (the legacy `/tasks/` endpoint is
// gone), and the activity timeline renders the whole log. Pull a generous page so early entries
// (the first task runs, repo selection) stay visible on reports with many findings — matching the
// limit the kickoff flow already uses to find the repo-selection artefact.
const ARTEFACT_FETCH_LIMIT = 1000

export interface InboxReportDetailLogicProps {
    reportId: string
    /** The selected report, fed in by the shell so task polling can stop once it reaches a terminal status. */
    report?: SignalReport | null
}

/** A linked task plus its derived purpose and when the association was first recorded. Mirrors desktop `ReportTaskData`. */
export interface ReportTaskEntry {
    task: Task
    purpose: ReportTaskPurpose
    purposeLabel: string
    startedAt: string
}

/**
 * Whether an implementation task still holds this report's single implementation slot, which makes a
 * manual "Create PR" fail with a `signal_report_task_cap` 429.
 *
 * Approximates the server predicate with what the client has: only `latest_run` rather than every
 * run, and a shipped PR is read off the report instead (`hasImplementationPr`). Unloaded tasks read
 * as no live implementation, so a cold load leaves the action enabled and the 429 stays the backstop
 * rather than blocking a legitimate first press.
 */
export function hasLiveImplementationTask(reportTasks: ReportTaskEntry[] | null): boolean {
    return (reportTasks ?? []).some(
        (entry) =>
            entry.purpose === 'implementation' &&
            !IMPLEMENTATION_SLOT_RELEASING_STATUSES.includes(entry.task.latest_run?.status ?? TaskRunStatus.NOT_STARTED)
    )
}

/**
 * Whether an implementation run is still moving, which is what the Create PR gate waits on.
 *
 * Unlike `hasLiveImplementationTask` this counts `completed` as settled, because a completed run
 * holds the report's slot for good and no later change can hand it back. Reusing the slot predicate
 * here would leave the poll running forever on a finished implementation.
 */
export function implementationRunInFlight(reportTasks: ReportTaskEntry[] | null): boolean {
    return (reportTasks ?? []).some(
        (entry) =>
            entry.purpose === 'implementation' &&
            !TERMINAL_RUN_STATUSES.includes(entry.task.latest_run?.status ?? TaskRunStatus.NOT_STARTED)
    )
}

// While the report is still being worked, poll linked tasks every 5s. Mirrors desktop.
const ACTIVE_STATUSES: SignalReportStatus[] = [
    SignalReportStatus.CANDIDATE,
    SignalReportStatus.IN_PROGRESS,
    SignalReportStatus.PENDING_INPUT,
]

const REPORT_TASKS_POLL_INTERVAL_MS = 5000

// PR CI checks refresh cadence while the detail is open — a running build's status stays current
// without hammering GitHub. Mirrors the desktop PR-review view's 15s poll.
const PR_CHECKS_POLL_INTERVAL_MS = 15000

// Back off the checks poll after this many consecutive failures: a PR GitHub can't return
// checks for (deleted branch, lost integration access) re-fails on every 15s tick for nothing.
const PR_CHECKS_MAX_CONSECUTIVE_FAILURES = 3

// While backed off, still retry every Nth tick (20 × 15s = 5 min) so a transient GitHub outage
// heals the section without the report having to be closed and reopened.
const PR_CHECKS_FAILURE_BACKOFF_TICKS = 20

/** Extract the PR url from a task's latest run output, if present. Mirrors desktop `getTaskPrUrl`. */
export function getTaskPrUrl(task: Task): string | null {
    const prUrl = task.latest_run?.output?.pr_url
    return typeof prUrl === 'string' && prUrl.length > 0 ? prUrl : null
}

/**
 * A PR comment plus client-only state layered on top of the generated shape: `pending` marks an
 * optimistic create/edit still in flight (or failed), so the UI can show it immediately instead of
 * letting it vanish during the request.
 */
export interface ClientPullRequestComment extends PullRequestCommentApi {
    pending?: 'sending' | 'failed'
}

/** An inline review-comment thread anchored to a diff line: the root comment plus its replies, in order. */
export interface ReviewThread {
    /** Root comment id — the id GitHub reply calls target. */
    rootId: string
    path: string
    /** Anchor line in the diff (the end line for multi-line comments). */
    line: number
    /** GitHub diff side: 'RIGHT' = additions, 'LEFT' = deletions. */
    side: 'LEFT' | 'RIGHT'
    comments: ClientPullRequestComment[]
}

/** A not-yet-posted thread the user opened on a diff line. */
export interface DraftThread {
    path: string
    line: number
    side: 'LEFT' | 'RIGHT'
}

/** Stable key for a thread or draft anchor, used for posting state and annotation metadata. */
export function threadKey(anchor: { path: string; line: number; side: string }): string {
    return `${anchor.path}:${anchor.side}:${anchor.line}`
}

/** Pull the most specific message out of a review-comment API error, falling back to `fallback`. */
function reviewCommentError(error: any, fallback: string): string {
    return error?.data?.error || error?.detail || error?.message || fallback
}

/**
 * Replace one comment in `comments`, leaving every other entry untouched. Optimistic updates and their
 * rollbacks both run against the current list, so a slow request finishing can't undo a delete, edit or
 * reaction that landed while it was in flight.
 */
function patchComment(
    comments: readonly PullRequestCommentApi[] | null,
    commentId: string,
    patch: (comment: ClientPullRequestComment) => ClientPullRequestComment
): PullRequestCommentApi[] {
    return (comments ?? []).map((c) => (c.id === commentId ? patch(c) : c))
}

/**
 * `explanation` text from the latest judgment artefact of `type`, or null. The priority/actionability
 * judgment artefacts already carry the agent's rationale — surfaced in the detail view without any extra fetch.
 */
function latestJudgmentExplanation(
    artefacts: SignalReportArtefact[] | null,
    type: 'priority_judgment' | 'actionability_judgment'
): string | null {
    const matching = (artefacts ?? []).filter((a) => a.type === type)
    if (matching.length === 0) {
        return null
    }
    const latest = matching.reduce((a, b) => (b.created_at > a.created_at ? b : a))
    const explanation = latest.content?.explanation
    return typeof explanation === 'string' && explanation.trim() ? explanation : null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxReportDetailLogicValues {
    personalIntegrations: PersonalGitHubIntegration[] // personalIntegrationsLogic
    actionabilityExplanation: string | null
    addReviewerOptions: AvailableReviewerOption[]
    availableReviewers: AvailableReviewerOption[] | null
    availableReviewersLoading: boolean
    chartIdsKey: string
    chartPlacements: ChartPlacements
    chartsById: Map<string, ReportChartApi>
    currentUserGithubLogin: string | null
    diffArtefactId: string | null
    displayReviewers: EnrichedReviewer[] | null
    draftThread: DraftThread | null
    editingCommentId: string | null
    expandedTaskIds: string[]
    feedbackNoteDraft: string
    feedbackNoteOpen: boolean
    feedbackNoteSent: boolean
    feedbackNoteSubmitting: boolean
    feedbackSentiment: InboxReportFeedbackSentiment | null
    hasImplementationPr: boolean
    hasLiveImplementationTask: boolean
    hasPersonalGithub: boolean
    inlineThreadCount: number
    inlineThreadsByFile: Record<string, ReviewThread[]>
    isReResearch: boolean
    isReportActive: boolean
    isUpdatingReviewers: boolean
    latestCommitArtefact: SignalReportArtefact | null
    optimisticReviewers: EnrichedReviewer[] | null
    postingThreadKey: string | null
    prChecks: readonly PullRequestCheckApi[] | null
    prChecksBackedOff: boolean
    prChecksConsecutiveFailures: number
    prChecksError: string | null
    prChecksLoading: boolean
    prComments: readonly PullRequestCommentApi[] | null
    prCommentsError: string | null
    prCommentsLoading: boolean
    primaryTask: ReportTaskEntry | null
    priorityExplanation: string | null
    report: SignalReport | null
    reportArtefacts: SignalReportArtefact[] | null
    reportArtefactsLoading: boolean
    reportCharts: ReportChartApi[]
    reportDiff: CommitDiffResponseApi | null
    reportDiffError: string | null
    reportDiffLoading: boolean
    reportReviewers: EnrichedReviewer[] | null
    reportSignals: SignalNode[] | null
    reportSignalsLoading: boolean
    reportSummary: string | null
    reportTasks: ReportTaskEntry[] | null
    reportTasksLoading: boolean
    selectedTask: ReportTaskEntry | null
    selectedTaskId: string | null
    shouldPollReportTasks: boolean
    trailingCharts: ReportChartApi[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxReportDetailLogicActions {
    createPrSuccess: () => {
        value: true
    } // inboxTaskKickoffLogic
    closeDraftThread: () => {
        value: true
    }
    deleteReviewComment: (commentId: string) => {
        commentId: string
    }
    editReviewComment: (
        commentId: string,
        body: string
    ) => {
        body: string
        commentId: string
    }
    loadAvailableReviewers: ({ query }?: { query?: string }) => {
        query?: string
    }
    loadAvailableReviewersFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAvailableReviewersSuccess: (
        availableReviewers: {
            email: string
            name: string
            user_uuid: string
        }[],
        payload?: {
            query?: string
        }
    ) => {
        availableReviewers: {
            email: string
            name: string
            user_uuid: string
        }[]
        payload?: {
            query?: string
        }
    }
    loadPrChecks: () => any
    loadPrChecksFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPrChecksSuccess: (
        prChecks: readonly PullRequestCheckApi[] | null,
        payload?: any
    ) => {
        prChecks: readonly PullRequestCheckApi[] | null
        payload?: any
    }
    loadPrComments: () => any
    loadPrCommentsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPrCommentsSuccess: (
        prComments: readonly PullRequestCommentApi[] | null,
        payload?: any
    ) => {
        prComments: readonly PullRequestCommentApi[] | null
        payload?: any
    }
    loadReportArtefacts: () => any
    loadReportArtefactsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReportArtefactsSuccess: (
        reportArtefacts: SignalReportArtefact[],
        payload?: any
    ) => {
        reportArtefacts: SignalReportArtefact[]
        payload?: any
    }
    loadReportDiff: ({ artefactId }: { artefactId: string }) => {
        artefactId: string
    }
    loadReportDiffFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReportDiffSuccess: (
        reportDiff: CommitDiffResponseApi | null,
        payload?: {
            artefactId: string
        }
    ) => {
        reportDiff: CommitDiffResponseApi | null
        payload?: {
            artefactId: string
        }
    }
    loadReportSignals: () => any
    loadReportSignalsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReportSignalsSuccess: (
        reportSignals: SignalNodeApi[],
        payload?: any
    ) => {
        reportSignals: SignalNodeApi[]
        payload?: any
    }
    loadReportTasks: () => any
    loadReportTasksFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReportTasksSuccess: (
        reportTasks: ReportTaskEntry[],
        payload?: any
    ) => {
        reportTasks: ReportTaskEntry[]
        payload?: any
    }
    openDraftThread: (draft: DraftThread) => {
        draft: DraftThread
    }
    openFeedbackNote: () => {
        value: true
    }
    postReviewComment: (payload: {
        body: string
        inReplyTo?: string
        /** Thread/draft key the composer belongs to, for per-thread posting state. */
        key: string
        line?: number
        path?: string
        side?: 'LEFT' | 'RIGHT'
    }) => {
        payload: {
            body: string
            inReplyTo?: string | undefined
            key: string
            line?: number | undefined
            path?: string | undefined
            side?: 'LEFT' | 'RIGHT' | undefined
        }
    }
    postReviewCommentFinished: () => {
        value: true
    }
    rateReport: (sentiment: InboxReportFeedbackSentiment) => {
        sentiment: InboxReportFeedbackSentiment
    }
    searchAvailableReviewers: (query: string) => {
        query: string
    }
    setEditingCommentId: (commentId: string | null) => {
        commentId: string | null
    }
    setFeedbackNoteDraft: (draft: string) => {
        draft: string
    }
    setFeedbackNoteSubmitting: (submitting: boolean) => {
        submitting: boolean
    }
    setOptimisticReviewers: (reviewers: EnrichedReviewer[] | null) => {
        reviewers: EnrichedReviewer[] | null
    }
    setReport: (report: SignalReport | null) => {
        report: SignalReport | null
    }
    setSelectedTaskId: (taskId: string | null) => {
        taskId: string | null
    }
    submitFeedbackNote: (note: string) => {
        note: string
    }
    toggleExpandedTask: (taskId: string) => {
        taskId: string
    }
    toggleReviewCommentReaction: (
        commentId: string,
        content: string
    ) => {
        commentId: string
        content: string
    }
    updateReviewers: (
        content: Record<string, string>[],
        optimistic: EnrichedReviewer[]
    ) => {
        content: Record<string, string>[]
        optimistic: EnrichedReviewer[]
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxReportDetailLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        isUpdatingReviewers: (optimisticReviewers: EnrichedReviewer[] | null) => boolean
        reportReviewers: (reportArtefacts: SignalReportArtefact[] | null) => EnrichedReviewer[] | null
        isReportActive: (report: SignalReport | null) => boolean
        shouldPollReportTasks: (isReportActive: boolean, reportTasks: ReportTaskEntry[] | null) => boolean
        hasImplementationPr: (report: SignalReport | null) => boolean
        prChecksBackedOff: (prChecksConsecutiveFailures: number) => boolean
        hasPersonalGithub: (personalIntegrations: PersonalGitHubIntegration[]) => boolean
        currentUserGithubLogin: (personalIntegrations: PersonalGitHubIntegration[]) => string | null
        inlineThreadsByFile: (prComments: readonly PullRequestCommentApi[] | null) => Record<string, ReviewThread[]>
        inlineThreadCount: (inlineThreadsByFile: Record<string, ReviewThread[]>) => number
        latestCommitArtefact: (reportArtefacts: SignalReportArtefact[] | null) => SignalReportArtefact | null
        reportCharts: (report: SignalReport | null) => ReportChartApi[]
        chartsById: (reportCharts: ReportChartApi[]) => Map<string, ReportChartApi>
        chartIdsKey: (reportCharts: ReportChartApi[]) => string
        reportSummary: (report: SignalReport | null) => string | null
        chartPlacements: (reportSummary: string | null, chartIdsKey: string) => ChartPlacements
        trailingCharts: (reportCharts: ReportChartApi[], chartPlacements: ChartPlacements) => ReportChartApi[]
        priorityExplanation: (reportArtefacts: SignalReportArtefact[] | null) => string | null
        actionabilityExplanation: (reportArtefacts: SignalReportArtefact[] | null) => string | null
        displayReviewers: (
            reportReviewers: EnrichedReviewer[] | null,
            optimisticReviewers: EnrichedReviewer[] | null,
            user: null | import('~/types').UserType
        ) => EnrichedReviewer[] | null
        addReviewerOptions: (
            availableReviewers: AvailableReviewerOption[] | null,
            user: null | import('~/types').UserType
        ) => AvailableReviewerOption[]
        isReResearch: (reportTasks: ReportTaskEntry[] | null) => boolean
        hasLiveImplementationTask: (reportTasks: ReportTaskEntry[] | null) => boolean
        primaryTask: (reportTasks: ReportTaskEntry[] | null) => ReportTaskEntry | null
        selectedTask: (
            reportTasks: ReportTaskEntry[] | null,
            selectedTaskId: string | null,
            primaryTask: ReportTaskEntry | null
        ) => ReportTaskEntry | null
    }
}

export type inboxReportDetailLogicType = MakeLogicType<
    inboxReportDetailLogicValues,
    inboxReportDetailLogicActions,
    InboxReportDetailLogicProps,
    inboxReportDetailLogicMeta
>

/**
 * Per-selected-report detail logic: artefacts, contributing signals, suggested reviewers, and linked tasks.
 * Keyed by `reportId` so each open report gets its own mounted instance. Does NOT import `inboxSceneLogic`
 * (the report id is passed in as a prop) to avoid a logic cycle.
 */
export const inboxReportDetailLogic = kea<inboxReportDetailLogicType>([
    path(['scenes', 'inbox', 'logics', 'inboxReportDetailLogic']),
    props({} as InboxReportDetailLogicProps),
    key((props) => props.reportId),

    connect(() => ({
        // Personal GitHub connection state gates the inline comment composer (comments post as the user).
        values: [personalIntegrationsLogic, ['integrations as personalIntegrations']],
        // Starting a PR task writes to the artefact log, which is where the Create PR gate reads from.
        actions: [inboxTaskKickoffLogic, ['createPrSuccess']],
    })),

    actions({
        // Open a not-yet-posted comment thread on a diff line (one draft at a time).
        openDraftThread: (draft: DraftThread) => ({ draft }),
        closeDraftThread: true,
        // Post an inline review comment: a reply when `inReplyTo` is set, else a new thread on the draft anchor.
        postReviewComment: (payload: {
            body: string
            inReplyTo?: string
            path?: string
            line?: number
            side?: 'LEFT' | 'RIGHT'
            /** Thread/draft key the composer belongs to, for per-thread posting state. */
            key: string
        }) => ({ payload }),
        postReviewCommentFinished: true,
        // Edit / delete one of the user's own review comments (optimistic, reverts on failure).
        editReviewComment: (commentId: string, body: string) => ({ commentId, body }),
        deleteReviewComment: (commentId: string) => ({ commentId }),
        // Add or remove the user's own reaction of `content` on a review comment (optimistic toggle).
        toggleReviewCommentReaction: (commentId: string, content: string) => ({ commentId, content }),
        // Which comment is being edited inline (null = none).
        setEditingCommentId: (commentId: string | null) => ({ commentId }),
        setReport: (report: SignalReport | null) => ({ report }),
        // Optimistically replace the reviewer list while the PUT is in flight, then reload from the server.
        // Addressed by report (not artefact) so a report with no reviewers yet can still be assigned one.
        // Mirrors desktop `useUpdateSuggestedReviewers` optimistic behavior.
        updateReviewers: (content: Record<string, string>[], optimistic: EnrichedReviewer[]) => ({
            content,
            optimistic,
        }),
        setOptimisticReviewers: (reviewers: EnrichedReviewer[] | null) => ({ reviewers }),
        // Debounced server-side org-member search for the add-reviewer picker.
        searchAvailableReviewers: (query: string) => ({ query }),
        // Which linked task's run log the detail view shows; null falls back to `primaryTask`.
        setSelectedTaskId: (taskId: string | null) => ({ taskId }),
        // Inline-expand a linked task's run log within the report detail's Runs section.
        toggleExpandedTask: (taskId: string) => ({ taskId }),
        // Thumbs feedback at the end of the report body. Recorded server-side as a report action
        // (consumption evidence) – nothing about the report's state changes.
        rateReport: (sentiment: InboxReportFeedbackSentiment) => ({ sentiment }),
        // Optional note, offered only after a rating is in. The rating is never held up waiting for it.
        openFeedbackNote: true,
        setFeedbackNoteDraft: (draft: string) => ({ draft }),
        // The note rides on the payload: the reducers below clear the draft, and listeners run after them.
        submitFeedbackNote: (note: string) => ({ note }),
        // Driven by the submit listener only, so the re-entrancy guard and the Send button's
        // loading state read the same flag.
        setFeedbackNoteSubmitting: (submitting: boolean) => ({ submitting }),
    }),

    loaders(({ props, values }) => ({
        reportArtefacts: [
            null as SignalReportArtefact[] | null,
            {
                loadReportArtefacts: async () => {
                    const response: SignalReportArtefactResponse = await api.signalReports.artefacts(props.reportId, {
                        limit: ARTEFACT_FETCH_LIMIT,
                    })
                    return response.results
                },
            },
        ],
        reportSignals: [
            null as SignalNode[] | null,
            {
                loadReportSignals: async () => {
                    const response = await signalsReportsSignalsRetrieve(
                        String(teamLogic.values.currentTeamId),
                        props.reportId
                    )
                    return response.signals
                },
            },
        ],
        reportTasks: [
            null as ReportTaskEntry[] | null,
            {
                // The task↔report association lives in the `task_run` artefact log: each artefact's
                // `(product, type)` derives the task's purpose. We group by task id (earliest
                // association wins for `startedAt`), drop `repo_selection` (pipeline plumbing), then
                // resolve each task. Mirrors desktop `useReportTasks`. Derives from the already-loaded
                // `reportArtefacts` (re-run after each artefact load) rather than re-fetching them.
                loadReportTasks: async () => {
                    const artefacts = values.reportArtefacts ?? []
                    const associations = new Map<
                        string,
                        { purpose: ReportTaskPurpose; purposeLabel: string; startedAt: string }
                    >()
                    for (const artefact of artefacts) {
                        if (artefact.type !== 'task_run') {
                            continue
                        }
                        const content = artefact.content as TaskRunArtefactContent
                        if (!content?.task_id) {
                            continue
                        }
                        const derived = deriveTaskPurpose(content)
                        if (!derived) {
                            continue
                        }
                        const existing = associations.get(content.task_id)
                        if (!existing) {
                            associations.set(content.task_id, { ...derived, startedAt: artefact.created_at })
                        } else if (artefact.created_at < existing.startedAt) {
                            // Keep the earliest association's timestamp + purpose for this task.
                            associations.set(content.task_id, { ...derived, startedAt: artefact.created_at })
                        }
                    }
                    const entries = await Promise.all(
                        [...associations.entries()].map(async ([taskId, meta]): Promise<ReportTaskEntry | null> => {
                            try {
                                const task = await api.tasks.get(taskId)
                                return { task, ...meta }
                            } catch {
                                // A deleted/inaccessible task drops out of the list rather than failing the load.
                                return null
                            }
                        })
                    )
                    return entries
                        .filter((entry): entry is ReportTaskEntry => entry !== null)
                        .sort(
                            (a, b) =>
                                PURPOSE_ORDER.indexOf(a.purpose) - PURPOSE_ORDER.indexOf(b.purpose) ||
                                new Date(a.startedAt).getTime() - new Date(b.startedAt).getTime()
                        )
                },
            },
        ],
        availableReviewers: [
            null as AvailableReviewerOption[] | null,
            {
                // Org members with a linked GitHub identity who can be added as reviewers.
                // Filtered server-side via `query` (the backend ranks + caps at 100) so the picker
                // isn't limited to the alphabetical first page. Empty query loads the default page.
                loadAvailableReviewers: async ({ query }: { query?: string } = {}) => {
                    return await api.signalReports.availableReviewers(query)
                },
            },
        ],
        // The report's branch diff (its `commit` artefact's branch vs the repo default branch), rendered
        // in the "Files changed" section. Loaded here rather than in the component so the fetch is keyed
        // to the report and cascades off the artefact load — once artefacts resolve we know the latest
        // commit artefact, and re-fetch only when a *new* commit lands (not on every 5s activity poll).
        reportDiff: [
            null as CommitDiffResponseApi | null,
            {
                loadReportDiff: async ({ artefactId }: { artefactId: string }) => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    return await signalsReportArtefactsDiff(String(teamId), props.reportId, artefactId)
                },
            },
        ],
        // CI checks on the report's implementation PR. Only fetched when the report has one; polled
        // every 15s while the detail is mounted (see the `setReport` listener) so a running build's
        // status stays current, mirroring the desktop PR-review view.
        prChecks: [
            null as readonly PullRequestCheckApi[] | null,
            {
                loadPrChecks: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    const response = await signalsReportPrChecks(String(teamId), props.reportId)
                    return response.checks
                },
            },
        ],
        // Conversation + review comments on the report's implementation PR, merged chronologically.
        prComments: [
            null as readonly PullRequestCommentApi[] | null,
            {
                loadPrComments: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    const response = await signalsReportPrComments(String(teamId), props.reportId)
                    return response.comments
                },
            },
        ],
    })),

    reducers({
        report: [
            null as SignalReport | null,
            {
                setReport: (_, { report }) => report,
            },
        ],
        // While a reviewer update is in flight, this overrides the artefact-derived list so the UI
        // reflects the change immediately. Cleared once the reload lands (or the update fails).
        optimisticReviewers: [
            null as EnrichedReviewer[] | null,
            {
                updateReviewers: (_, { optimistic }) => optimistic,
                setOptimisticReviewers: (_, { reviewers }) => reviewers,
            },
        ],
        // Explicit task selection for the run-log viewer. Reset when the report changes so a freshly
        // opened run starts on its `primaryTask`.
        selectedTaskId: [
            null as string | null,
            {
                setSelectedTaskId: (_, { taskId }) => taskId,
                setReport: () => null,
            },
        ],
        // Linked tasks whose run log is expanded inline in the Runs section. Reset when the report
        // changes so a freshly opened report starts with everything collapsed.
        expandedTaskIds: [
            [] as string[],
            {
                toggleExpandedTask: (state, { taskId }) =>
                    state.includes(taskId) ? state.filter((id) => id !== taskId) : [...state, taskId],
                setReport: () => [],
            },
        ],
        // The thumbs rating this reader gave the open report, so the row can read the choice back.
        // The logic is keyed by report id, so each report keeps its own rating for as long as it's open.
        feedbackSentiment: [
            null as InboxReportFeedbackSentiment | null,
            {
                rateReport: (_, { sentiment }) => sentiment,
            },
        ],
        // Whether the optional note field is showing. Switching the rating closes an unsent note so
        // the draft can't end up attached to a sentiment the reader has since changed their mind about.
        feedbackNoteOpen: [
            false,
            {
                openFeedbackNote: () => true,
                rateReport: () => false,
                submitFeedbackNote: () => false,
            },
        ],
        feedbackNoteDraft: [
            '',
            {
                setFeedbackNoteDraft: (_, { draft }) => draft,
                rateReport: () => '',
                submitFeedbackNote: () => '',
            },
        ],
        feedbackNoteSent: [
            false,
            {
                submitFeedbackNote: () => true,
                rateReport: () => false,
            },
        ],
        feedbackNoteSubmitting: [
            false,
            {
                setFeedbackNoteSubmitting: (_, { submitting }) => submitting,
            },
        ],
        // Human-readable diff-load failure (kea-loaders only exposes a boolean loading flag). A failed
        // compare usually means the branch was merged, deleted, or force-rewritten away.
        reportDiffError: [
            null as string | null,
            {
                loadReportDiff: () => null,
                loadReportDiffSuccess: () => null,
                loadReportDiffFailure: () =>
                    "Couldn't load the diff. The branch may have been merged, deleted, or rewritten.",
            },
        ],
        // The commit artefact the current `reportDiff` was loaded for, so the artefact poll re-fetches
        // the diff only when a new commit lands rather than on every tick.
        diffArtefactId: [
            null as string | null,
            {
                loadReportDiff: (_, { artefactId }) => artefactId,
            },
        ],
        // Human-readable PR checks/comments load failures (kea-loaders only exposes a boolean flag).
        // A failure usually means the branch/PR was deleted or the GitHub integration lost access.
        // Cleared only on success (not on load start), so the section keeps showing the error while
        // a backed-off retry is in flight instead of flashing back to the loading skeleton.
        prChecksError: [
            null as string | null,
            {
                loadPrChecksSuccess: () => null,
                loadPrChecksFailure: () => "Couldn't load the PR checks from GitHub.",
            },
        ],
        // Consecutive failed checks fetches — feeds `prChecksBackedOff`.
        prChecksConsecutiveFailures: [
            0,
            {
                loadPrChecksSuccess: () => 0,
                loadPrChecksFailure: (state: number) => state + 1,
            },
        ],
        prCommentsError: [
            null as string | null,
            {
                loadPrComments: () => null,
                loadPrCommentsSuccess: () => null,
                loadPrCommentsFailure: () => "Couldn't load the PR comments from GitHub.",
            },
        ],
        // The one in-progress draft thread on a diff line. Reset when the report changes.
        draftThread: [
            null as DraftThread | null,
            {
                openDraftThread: (_, { draft }) => draft,
                closeDraftThread: () => null,
                setReport: () => null,
            },
        ],
        // Which thread's composer has a post in flight — gates its submit button and textarea.
        postingThreadKey: [
            null as string | null,
            {
                postReviewComment: (_, { payload }) => payload.key,
                postReviewCommentFinished: () => null,
            },
        ],
        // Which comment is open for inline editing. Cleared on a successful edit or when the report changes.
        editingCommentId: [
            null as string | null,
            {
                setEditingCommentId: (_, { commentId }) => commentId,
                setReport: () => null,
            },
        ],
    }),

    selectors({
        // Mirrors the optimistic override lifecycle: an update is in flight exactly while the
        // optimistic list is set (cleared once the reload lands or the update fails).
        isUpdatingReviewers: [
            (s) => [s.optimisticReviewers],
            (optimisticReviewers: EnrichedReviewer[] | null) => optimisticReviewers !== null,
        ],
        reportReviewers: [
            (s) => [s.reportArtefacts],
            (reportArtefacts: SignalReportArtefact[] | null): EnrichedReviewer[] | null => {
                if (!reportArtefacts) {
                    return null
                }
                const reviewersArtefact = reportArtefacts.find((a) => a.type === 'suggested_reviewers')
                if (!reviewersArtefact) {
                    return null
                }
                return reviewersArtefact.content as unknown as EnrichedReviewer[]
            },
        ],
        isReportActive: [
            (s) => [s.report],
            (report: SignalReport | null): boolean => (report ? ACTIVE_STATUSES.includes(report.status) : false),
        ],
        // Poll the artefact log while something can still change it. A report being worked is the usual
        // case, but a `ready` report can hold an implementation run too, and that run settling is what
        // hands the Create PR slot back. Without this clause the action stays disabled on a ready report
        // until the pane is reopened, and the server's 429 cannot correct it because the failure runs the
        // other way: the press is refused in the UI that the server would now accept.
        shouldPollReportTasks: [
            (s) => [s.isReportActive, s.reportTasks],
            (isReportActive: boolean, reportTasks: ReportTaskEntry[] | null): boolean =>
                isReportActive || implementationRunInFlight(reportTasks),
        ],
        // Whether the report has a shipped implementation PR — gates the PR checks/comments fetch + poll.
        hasImplementationPr: [
            (s) => [s.report],
            (report: SignalReport | null): boolean => !!report?.implementation_pr_url,
        ],
        // True once GitHub has failed enough consecutive times that the 15s cadence stops being worth
        // it — the poll tick then drops to a slow retry (see PR_CHECKS_FAILURE_BACKOFF_TICKS).
        prChecksBackedOff: [
            (s) => [s.prChecksConsecutiveFailures],
            (prChecksConsecutiveFailures: number): boolean =>
                prChecksConsecutiveFailures >= PR_CHECKS_MAX_CONSECUTIVE_FAILURES,
        ],
        // Whether the current user has a personal GitHub connection — required to post review comments
        // (they're attributed to the user's own GitHub identity, not the app's).
        hasPersonalGithub: [
            (s) => [s.personalIntegrations],
            (personalIntegrations: PersonalGitHubIntegration[]): boolean => (personalIntegrations ?? []).length > 0,
        ],
        // The current user's GitHub login (from their personal connection) — used to attribute optimistic
        // comments and to tell which comments/reactions are the user's own (editable/removable). Note this
        // is `github_login`, NOT `account.name` (which is the installation's org/user, e.g. "PostHog").
        currentUserGithubLogin: [
            (s) => [s.personalIntegrations],
            (personalIntegrations: PersonalGitHubIntegration[]): string | null =>
                personalIntegrations?.[0]?.github_login ?? null,
        ],
        // Inline review threads grouped by file path: thread roots (review comments with a line anchor
        // and no in_reply_to) plus their replies, in chronological order. Outdated comments (null line)
        // are excluded here — they still show in the Comments section.
        inlineThreadsByFile: [
            (s) => [s.prComments],
            (prComments: readonly PullRequestCommentApi[] | null): Record<string, ReviewThread[]> => {
                if (!prComments) {
                    return {}
                }
                const threads = new Map<string, ReviewThread>()
                for (const comment of prComments) {
                    if (comment.comment_type !== 'review' || !comment.path || comment.in_reply_to_id) {
                        continue
                    }
                    if (comment.line == null) {
                        continue
                    }
                    threads.set(comment.id, {
                        rootId: comment.id,
                        path: comment.path,
                        line: comment.line,
                        side: comment.side === 'LEFT' ? 'LEFT' : 'RIGHT',
                        comments: [comment],
                    })
                }
                for (const comment of prComments) {
                    if (comment.comment_type !== 'review' || !comment.in_reply_to_id) {
                        continue
                    }
                    threads.get(comment.in_reply_to_id)?.comments.push(comment)
                }
                const byFile: Record<string, ReviewThread[]> = {}
                for (const thread of threads.values()) {
                    ;(byFile[thread.path] ??= []).push(thread)
                }
                return byFile
            },
        ],
        // Total inline threads, for the Files changed toolbar summary.
        inlineThreadCount: [
            (s) => [s.inlineThreadsByFile],
            (inlineThreadsByFile: Record<string, ReviewThread[]>): number =>
                Object.values(inlineThreadsByFile).reduce((sum, threads) => sum + threads.length, 0),
        ],
        // The most recent `commit` artefact — its branch is treated as the report's branch to diff
        // against the repository default branch. A report's code work may span several pushes; the
        // latest commit's branch tip is the current state worth inspecting.
        latestCommitArtefact: [
            (s) => [s.reportArtefacts],
            (reportArtefacts: SignalReportArtefact[] | null): SignalReportArtefact | null => {
                const commits = (reportArtefacts ?? []).filter((a) => a.type === 'commit')
                if (commits.length === 0) {
                    return null
                }
                return commits.reduce((latest, a) => (a.created_at > latest.created_at ? a : latest))
            },
        ],
        reportCharts: [(s) => [s.report], (report: SignalReport | null): ReportChartApi[] => report?.charts ?? []],
        chartsById: [
            (s) => [s.reportCharts],
            (reportCharts: ReportChartApi[]): Map<string, ReportChartApi> =>
                new Map(reportCharts.map((chart) => [chart.chart_id, chart])),
        ],
        // A string rather than the id array, so the selectors below hold their identity while a report
        // polls. Artefacts reload on a timer and hand back a fresh array whether or not anything
        // changed, and the same is true of a refresh that appends a new version of one chart — but
        // placement only ever depends on *which* charts exist, so an equal key means an equal answer.
        chartIdsKey: [
            (s) => [s.reportCharts],
            (reportCharts: ReportChartApi[]): string => reportCharts.map((chart) => chart.chart_id).join('\n'),
        ],
        // Where each chart is drawn: a `chart:` link places its chart at that point in the prose, and
        // every chart the summary doesn't place follows it. A reference the placement pass rejected (a
        // repeat, one inside a table cell) still reads as its label — the reference decides where a
        // chart goes, not whether it shows at all.
        // Taken off `report` as its own value for the same reason: the shell hands the detail a fresh
        // report object as it polls, and the summary is the only part of it placement reads.
        reportSummary: [(s) => [s.report], (report: SignalReport | null): string | null => report?.summary ?? null],
        chartPlacements: [
            (s) => [s.reportSummary, s.chartIdsKey],
            (reportSummary: string | null, chartIdsKey: string): ChartPlacements =>
                resolveChartPlacements(reportSummary, chartIdsKey ? chartIdsKey.split('\n') : []),
        ],
        trailingCharts: [
            (s) => [s.reportCharts, s.chartPlacements],
            (reportCharts: ReportChartApi[], chartPlacements: ChartPlacements): ReportChartApi[] =>
                reportCharts.filter((chart) => !chartPlacements.inlineIds.has(chart.chart_id)),
        ],
        // Rationale behind the priority / actionability judgments, pulled from the already-loaded artefacts.
        priorityExplanation: [
            (s) => [s.reportArtefacts],
            (reportArtefacts: SignalReportArtefact[] | null): string | null =>
                latestJudgmentExplanation(reportArtefacts, 'priority_judgment'),
        ],
        actionabilityExplanation: [
            (s) => [s.reportArtefacts],
            (reportArtefacts: SignalReportArtefact[] | null): string | null =>
                latestJudgmentExplanation(reportArtefacts, 'actionability_judgment'),
        ],
        // The reviewer list to render: optimistic override (if any) wins over the artefact-derived list,
        // then the current user is pinned to the top. Mirrors desktop `displayReviewers`.
        displayReviewers: [
            (s) => [s.reportReviewers, s.optimisticReviewers, userLogic.selectors.user],
            (
                reportReviewers: EnrichedReviewer[] | null,
                optimisticReviewers: EnrichedReviewer[] | null,
                user: { uuid: string } | null
            ): EnrichedReviewer[] | null => {
                const reviewers = optimisticReviewers ?? reportReviewers
                if (!reviewers) {
                    return null
                }
                const meUuid = user?.uuid
                if (!meUuid) {
                    return reviewers
                }
                const meIndex = reviewers.findIndex((r) => r.user?.uuid === meUuid)
                if (meIndex <= 0) {
                    return reviewers
                }
                return [reviewers[meIndex], ...reviewers.filter((_, i) => i !== meIndex)]
            },
        ],
        // Add-reviewer options: org members with GitHub, current user pinned first ("Me"). Mirrors desktop.
        addReviewerOptions: [
            (s) => [s.availableReviewers, userLogic.selectors.user],
            (
                availableReviewers: AvailableReviewerOption[] | null,
                currentUser: { uuid: string; first_name?: string; last_name?: string; email?: string } | null
            ): AvailableReviewerOption[] => {
                const me: CurrentReviewerUser | null = currentUser
                    ? {
                          uuid: currentUser.uuid,
                          first_name: currentUser.first_name,
                          last_name: currentUser.last_name,
                          email: currentUser.email,
                      }
                    : null
                return buildAddReviewerOptions(availableReviewers ?? [], me)
            },
        ],
        // True when a re-research is under way: ≥2 research tasks, one currently in-flight while a prior
        // attempt already reached a terminal state. Mirrors desktop `AgentRunDetail`'s `isReResearch`.
        isReResearch: [
            (s) => [s.reportTasks],
            (reportTasks: ReportTaskEntry[] | null): boolean => {
                if (!reportTasks) {
                    return false
                }
                const researchTasks = reportTasks.filter((rt) => rt.purpose === 'research')
                if (researchTasks.length < 2) {
                    return false
                }
                const hasInFlight = researchTasks.some((rt) => {
                    const status = rt.task.latest_run?.status
                    return !!status && !TERMINAL_RUN_STATUSES.includes(status)
                })
                const hasPriorTerminal = researchTasks.some((rt) => {
                    const status = rt.task.latest_run?.status
                    return !!status && TERMINAL_RUN_STATUSES.includes(status)
                })
                return hasInFlight && hasPriorTerminal
            },
        ],
        hasLiveImplementationTask: [
            (s) => [s.reportTasks],
            (reportTasks: ReportTaskEntry[] | null): boolean => hasLiveImplementationTask(reportTasks),
        ],
        // The default task whose run log is shown: prefer one still in motion, tie-break by most-recent
        // link. Mirrors desktop `AgentRunDetail`'s `pickPrimaryTask`.
        primaryTask: [
            (s) => [s.reportTasks],
            (reportTasks: ReportTaskEntry[] | null): ReportTaskEntry | null => {
                if (!reportTasks || reportTasks.length === 0) {
                    return null
                }
                return [...reportTasks].sort((a, b) => {
                    const aInMotion = !TERMINAL_RUN_STATUSES.includes(
                        a.task.latest_run?.status ?? TaskRunStatus.NOT_STARTED
                    )
                    const bInMotion = !TERMINAL_RUN_STATUSES.includes(
                        b.task.latest_run?.status ?? TaskRunStatus.NOT_STARTED
                    )
                    if (aInMotion !== bInMotion) {
                        return aInMotion ? -1 : 1
                    }
                    return new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime()
                })[0]
            },
        ],
        // The linked task the viewer renders: the explicit selection if it still exists, else `primaryTask`.
        selectedTask: [
            (s) => [s.reportTasks, s.selectedTaskId, s.primaryTask],
            (
                reportTasks: ReportTaskEntry[] | null,
                selectedTaskId: string | null,
                primaryTask: ReportTaskEntry | null
            ): ReportTaskEntry | null => reportTasks?.find((rt) => rt.task.id === selectedTaskId) ?? primaryTask,
        ],
    }),

    listeners(({ actions, values, props }) => ({
        rateReport: ({ sentiment }) => {
            if (!values.report) {
                return
            }
            captureInboxReportFeedback({ report: values.report, sentiment, surface: 'detail_footer' })
            // Best-effort server-side record of the bare rating: consumption evidence the scout
            // inactivity sweep reads, so rating a report keeps its scout from being auto-paused.
            // The analytics event above stays the durable record of the rating itself.
            void signalsReportsFeedbackCreate(String(teamLogic.values.currentTeamId), values.report.id, {
                sentiment,
            }).catch(() => {})
        },
        // Fires on its own event so the rating stays exactly one `Inbox report feedback` per click.
        submitFeedbackNote: async ({ note }) => {
            const trimmed = note.trim()
            if (!values.report || !values.feedbackSentiment || !trimmed) {
                return
            }
            // Re-entrancy guard: the send button hides on submit, but a double-click within the same
            // frame can dispatch this twice before React unmounts it. `leave_note` mints a new row per
            // call, so bail before a second POST leaves the scout a duplicate steering note. The flag
            // resets in `finally` so a revised note (after re-rating) can still submit, and the Send
            // button shows it as a loading state in the meantime.
            if (values.feedbackNoteSubmitting) {
                return
            }
            actions.setFeedbackNoteSubmitting(true)
            const sentiment = values.feedbackSentiment
            try {
                captureInboxReportFeedbackNote({
                    report: values.report,
                    sentiment,
                    note: trimmed,
                    surface: 'detail_footer',
                })
                // Best-effort: also carry the note into the scout steering channel so the scout that filed
                // the report reads it next run. The analytics event above is the durable record, so a
                // failure here is swallowed rather than surfaced — the note is already captured.
                try {
                    await signalsReportsFeedbackCreate(String(teamLogic.values.currentTeamId), values.report.id, {
                        sentiment,
                        note: trimmed,
                    })
                } catch {
                    // no-op: forwarding is a convenience on top of the recorded feedback
                }
            } finally {
                actions.setFeedbackNoteSubmitting(false)
            }
        },
        searchAvailableReviewers: async ({ query }, breakpoint) => {
            await breakpoint(300)
            actions.loadAvailableReviewers({ query: query.trim() || undefined })
        },
        // Persist a reviewer add/remove. The optimistic list is already in place (set by the action's
        // reducer); on success reload the artefact so we converge on the server's enriched data, and on
        // failure clear the optimistic override so the UI snaps back. Mirrors desktop `useUpdateSuggestedReviewers`.
        updateReviewers: async ({ content }) => {
            try {
                await api.signalReports.setReviewers(props.reportId, content)
                await actions.loadReportArtefacts()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to update reviewers')
            } finally {
                // Clear the optimistic override; the freshly-loaded artefact is now the source of truth.
                actions.setOptimisticReviewers(null)
            }
        },
        // Post an inline review comment as the user. The comment is inserted optimistically (marked
        // `pending: 'sending'`) and the composer/draft closes immediately, so nothing vanishes during
        // the request. On success the optimistic entry is replaced by the real comment; on failure it's
        // flagged `pending: 'failed'` (kept visible so the text isn't lost) and a toast explains why.
        postReviewComment: async ({ payload }) => {
            const teamId = teamLogic.values.currentTeamId
            const tempId = `optimistic-${payload.key}-${values.prComments?.length ?? 0}-${payload.body.length}`
            const login = values.currentUserGithubLogin
            const optimistic: ClientPullRequestComment = {
                id: tempId,
                pending: 'sending',
                author: login,
                author_avatar_url: login ? `https://github.com/${login}.png` : null,
                body: payload.body,
                created_at: new Date().toISOString(),
                url: null,
                comment_type: 'review',
                path: payload.path ?? null,
                line: payload.line ?? null,
                start_line: null,
                side: payload.side ?? 'RIGHT',
                diff_hunk: null,
                in_reply_to_id: payload.inReplyTo ?? null,
                commit_id: null,
                reactions: [],
            }
            actions.loadPrCommentsSuccess([...(values.prComments ?? []), optimistic])
            actions.closeDraftThread()
            try {
                const response = await signalsReportPrReviewCommentsCreate(String(teamId), props.reportId, {
                    body: payload.body,
                    in_reply_to: payload.inReplyTo ?? null,
                    path: payload.path ?? null,
                    line: payload.line ?? null,
                    side: payload.side ?? null,
                })
                actions.loadPrCommentsSuccess(
                    (values.prComments ?? []).map((c) => (c.id === tempId ? response.comment : c))
                )
            } catch (error: any) {
                actions.loadPrCommentsSuccess(
                    (values.prComments ?? []).map((c) =>
                        c.id === tempId ? { ...(c as ClientPullRequestComment), pending: 'failed' } : c
                    )
                )
                lemonToast.error(reviewCommentError(error, "Couldn't post the comment to GitHub"))
            } finally {
                actions.postReviewCommentFinished()
            }
        },
        // Edit one of the user's own review comments. Optimistically swaps the body in; a failure puts
        // back only that comment's body.
        editReviewComment: async ({ commentId, body }) => {
            const teamId = teamLogic.values.currentTeamId
            const previous = (values.prComments ?? []).find((c) => c.id === commentId)
            actions.setEditingCommentId(null)
            if (!teamId || !previous) {
                return
            }
            actions.loadPrCommentsSuccess(
                patchComment(values.prComments, commentId, (c) => ({ ...c, body, pending: 'sending' }))
            )
            try {
                const response = await signalsReportPrReviewCommentUpdate(String(teamId), props.reportId, commentId, {
                    body,
                })
                actions.loadPrCommentsSuccess(patchComment(values.prComments, commentId, () => response.comment))
            } catch (error: any) {
                actions.loadPrCommentsSuccess(
                    patchComment(values.prComments, commentId, (c) => ({
                        ...c,
                        body: previous.body,
                        pending: undefined,
                    }))
                )
                lemonToast.error(reviewCommentError(error, "Couldn't save the edit"))
            }
        },
        // Delete one of the user's own review comments. Optimistically removes it; a failure slots it
        // back at its old index in the list as it stands now.
        deleteReviewComment: async ({ commentId }) => {
            const teamId = teamLogic.values.currentTeamId
            const index = (values.prComments ?? []).findIndex((c) => c.id === commentId)
            if (!teamId || index === -1) {
                return
            }
            const removed = (values.prComments ?? [])[index]
            actions.loadPrCommentsSuccess((values.prComments ?? []).filter((c) => c.id !== commentId))
            try {
                await signalsReportPrReviewCommentDestroy(String(teamId), props.reportId, commentId)
            } catch (error: any) {
                const current = (values.prComments ?? []).filter((c) => c.id !== commentId)
                actions.loadPrCommentsSuccess([...current.slice(0, index), removed, ...current.slice(index)])
                lemonToast.error(reviewCommentError(error, "Couldn't delete the comment"))
            }
        },
        // Toggle the user's own reaction of `content` on a comment. Optimistically adds/removes the
        // reaction, then confirms with the server (add returns the real reaction id). A failure puts back
        // only that one reaction, so a reaction toggled concurrently on the same comment isn't clobbered.
        toggleReviewCommentReaction: async ({ commentId, content }) => {
            const teamId = teamLogic.values.currentTeamId
            const login = values.currentUserGithubLogin
            if (!teamId || !login) {
                return
            }
            const comment = (values.prComments ?? []).find((c) => c.id === commentId)
            const mine = comment?.reactions?.find((r) => r.content === content && r.user_login === login)

            if (mine) {
                actions.loadPrCommentsSuccess(
                    patchComment(values.prComments, commentId, (c) => ({
                        ...c,
                        reactions: (c.reactions ?? []).filter((r) => r.id !== mine.id),
                    }))
                )
                try {
                    await signalsReportPrReviewCommentReactionDestroy(
                        String(teamId),
                        props.reportId,
                        commentId,
                        mine.id
                    )
                } catch (error: any) {
                    actions.loadPrCommentsSuccess(
                        patchComment(values.prComments, commentId, (c) => ({
                            ...c,
                            reactions: [...(c.reactions ?? []).filter((r) => r.id !== mine.id), mine],
                        }))
                    )
                    lemonToast.error(reviewCommentError(error, "Couldn't remove the reaction"))
                }
                return
            }

            const tempId = `optimistic-rx-${commentId}-${content}`
            const optimisticReaction: PullRequestCommentReactionApi = { id: tempId, content, user_login: login }
            actions.loadPrCommentsSuccess(
                patchComment(values.prComments, commentId, (c) => ({
                    ...c,
                    reactions: [...(c.reactions ?? []), optimisticReaction],
                }))
            )
            try {
                const response = await signalsReportPrReviewCommentReactionsCreate(
                    String(teamId),
                    props.reportId,
                    commentId,
                    { content: content as any }
                )
                actions.loadPrCommentsSuccess(
                    patchComment(values.prComments, commentId, (c) => ({
                        ...c,
                        reactions: (c.reactions ?? []).map((r) => (r.id === tempId ? response.reaction : r)),
                    }))
                )
            } catch (error: any) {
                actions.loadPrCommentsSuccess(
                    patchComment(values.prComments, commentId, (c) => ({
                        ...c,
                        reactions: (c.reactions ?? []).filter((r) => r.id !== tempId),
                    }))
                )
                lemonToast.error(reviewCommentError(error, "Couldn't add the reaction"))
            }
        },
        // The artefact log is the single source for the activity timeline AND the task associations,
        // so deriving the linked tasks hangs off each successful artefact load rather than issuing a
        // second identical fetch. The branch diff also cascades from here (once artefacts resolve we
        // know the latest commit artefact), but only re-fetches when a *new* commit lands.
        loadReportArtefactsSuccess: () => {
            actions.loadReportTasks()
            const commit = values.latestCommitArtefact
            if (commit && commit.id !== values.diffArtefactId) {
                actions.loadReportDiff({ artefactId: commit.id })
            }
        },
        // A PR task started from this pane is not in the artefact log the gate was computed from, so
        // refresh it. This is also what starts the task poll for a ready report, whose status alone
        // never gets one going.
        createPrSuccess: () => {
            actions.loadReportArtefacts()
        },
        setReport: () => {
            // Load the PR checks/comments once the report has a shipped PR. The recurring checks poll
            // is registered once in `afterMount` (not here) so it isn't torn down and restarted every
            // time the shell hands us a fresh `report` prop — which would starve the 15s cadence.
            // A failed load leaves the value null, so gate on the error too: without it every prop
            // churn from the shell's list poll would re-fetch (and re-fail) a PR GitHub can't serve.
            if (values.hasImplementationPr) {
                if (values.prChecks === null && !values.prChecksLoading && values.prChecksError === null) {
                    actions.loadPrChecks()
                }
                if (values.prComments === null && !values.prCommentsLoading && values.prCommentsError === null) {
                    actions.loadPrComments()
                }
            }
        },
    })),

    propsChanged(({ actions, props }, oldProps) => {
        // The shell re-renders the detail with a refreshed `selectedReport`; re-gate polling on the new status.
        if (props.report !== oldProps.report) {
            actions.setReport(props.report ?? null)
        }
    }),

    afterMount(({ actions, props, values, cache }) => {
        // `loadReportTasks` is cascaded from `loadReportArtefactsSuccess`, so it isn't called here.
        actions.loadReportArtefacts()
        actions.loadReportSignals()
        actions.loadAvailableReviewers()
        // Seed the report from props so polling is gated on its status from the first tick.
        actions.setReport(props.report ?? null)
        // Register the artefact-log poll once for the lifetime of the mount and let each tick decide
        // whether to fetch. Re-arming it from `setReport` instead would reset the 5s cadence on every
        // report prop the shell hands down, which is the starvation the PR-checks poll below avoids.
        // Auto-disposed on unmount / hidden tab.
        cache.disposables.add(() => {
            const interval = setInterval(() => {
                if (!values.shouldPollReportTasks) {
                    return
                }
                actions.loadReportArtefacts()
            }, REPORT_TASKS_POLL_INTERVAL_MS)
            return () => clearInterval(interval)
        }, 'reportTasksPoll')
        // Register the PR-checks poll once for the lifetime of the mount — the tick re-checks whether
        // the report has a PR (and whether GitHub keeps failing), so it stays correct as the report
        // prop churns without the interval ever being torn down and restarted (which would keep
        // resetting the 15s cadence). Auto-disposed on unmount / hidden tab.
        cache.disposables.add(() => {
            let tick = 0
            const interval = setInterval(() => {
                tick += 1
                if (!values.hasImplementationPr) {
                    return
                }
                // While backed off, only every Nth tick retries — enough for a transient GitHub
                // outage to heal the section without hammering a permanently broken PR.
                if (values.prChecksBackedOff && tick % PR_CHECKS_FAILURE_BACKOFF_TICKS !== 0) {
                    return
                }
                actions.loadPrChecks()
            }, PR_CHECKS_POLL_INTERVAL_MS)
            return () => clearInterval(interval)
        }, 'prChecksPoll')
    }),
])
