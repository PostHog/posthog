import { ApiError, NotSignedInError } from '@/api/client'
import { fetchReport } from '@/api/reports'
import { createTask, getTask, type HandoffRunFieldsApi, startTaskRun } from '@/api/tasks'
import { isRecord } from '@/lib/records'

import { type Clock, realClock } from './clock'
import { buildCreatePrReportPrompt } from './prompt'

const WARM_RETRY_HEADER = 'X-PostHog-Warm-Retry'
const WARM_RETRY_WINDOW_MS = 20_000
const WARM_RETRY_FIRST_DELAY_MS = 250
const WARM_RETRY_MAX_DELAY_MS = 1000

const FALLBACK_TITLE = 'Implement report fix'

function warmRetryToken(error: unknown): string | undefined {
    if (!(error instanceof ApiError) || error.status !== 503 || error.code !== 'warm_run_activation_unavailable') {
        return undefined
    }
    const token = isRecord(error.body) ? error.body.retry_token : undefined
    return typeof token === 'string' && token.trim() ? token : undefined
}

// Only the server can confirm nondelivery, and its first token pins every retry to the original run, so the first
// token is kept for all retries. Mirrors the web's `submitWithWarmRunRetry`.
export async function withWarmRetry<T>(
    send: (headers: Record<string, string>) => Promise<T>,
    options: { signal?: AbortSignal; clock?: Clock } = {}
): Promise<T> {
    const clock = options.clock ?? realClock
    const deadline = clock.now() + WARM_RETRY_WINDOW_MS
    let token: string | undefined
    let delay = WARM_RETRY_FIRST_DELAY_MS
    for (;;) {
        try {
            return await send(token ? { [WARM_RETRY_HEADER]: token } : {})
        } catch (error) {
            const next = warmRetryToken(error)
            const remaining = deadline - clock.now()
            if (!next || options.signal?.aborted || remaining <= 0) {
                throw error
            }
            token ??= next
            await clock.sleep(Math.min(delay, remaining), options.signal)
            delay = Math.min(delay * 2, WARM_RETRY_MAX_DELAY_MS)
        }
    }
}

export class RunNotStartedError extends Error {
    constructor() {
        super("PostHog created the task but couldn't start it. Try again.")
        this.name = 'RunNotStartedError'
    }
}

export interface KickoffResult {
    taskId: string
    runId: string
}

export interface KickoffOptions {
    run: HandoffRunFieldsApi
    taskId?: string
    onTaskCreated?: (taskId: string) => void
    signal?: AbortSignal
    clock?: Clock
}

// Makes the same two calls as the web's Create PR. The prompt reads the report fresh so it matches what the web sends.
// The task carries no repository: the server resolves it for report tasks and rejects one the client sets.
export async function kickOffReportTask(reportId: string, options: KickoffOptions): Promise<KickoffResult> {
    const report = await fetchReport(reportId, options.signal)
    const prompt = buildCreatePrReportPrompt(report)
    const taskId = report.assignee?.kind === 'task' ? (report.assignee.task_id ?? options.taskId) : options.taskId
    const task = taskId
        ? await getTask(taskId, options.signal)
        : await withWarmRetry(
              (headers) =>
                  createTask(
                      {
                          title: report.title?.trim() || FALLBACK_TITLE,
                          description: prompt,
                          origin_product: 'signal_report',
                          signal_report: reportId,
                          signal_report_task_relationship: 'implementation',
                      },
                      { headers, signal: options.signal }
                  ),
              options
          )
    if (task.signal_report !== reportId) {
        throw new RunNotStartedError()
    }
    options.onTaskCreated?.(task.id)
    let run = task.latest_run ?? null
    if (!run) {
        const running = await withWarmRetry(
            (headers) =>
                startTaskRun(
                    task.id,
                    {
                        run_source: 'signal_report',
                        signal_report_id: reportId,
                        // Interactive, not background: only interactive runs relay the agent's questions.
                        mode: 'interactive',
                        // The agent server delivers this as the first turn; without it the run idles.
                        pending_user_message: prompt,
                        ...options.run,
                    },
                    { headers, signal: options.signal }
                ),
            options
        )
        run = running.run ?? running.latest_run ?? null
    }
    if (!run) {
        throw new RunNotStartedError()
    }
    return { taskId: task.id, runId: run.id }
}

const FREE_TRIAL_COPY =
    "During your free trial, Self-driving writes reports but doesn't open pull requests. Contact us to upgrade."
const PR_LIMIT_COPY =
    'Your organization reached its self-driving pull request limit. Ask an org admin to raise it from the Inbox usage widget.'
const TASK_LIMIT_COPY = 'Task limit reached for this report. Try again later.'

/** Server copy from a tasks API error body: `error` on task errors, `detail` on DRF errors. */
function serverCopy(error: ApiError): string | undefined {
    const body = isRecord(error.body) ? error.body : {}
    const text = typeof body.error === 'string' && body.error.trim() ? body.error : error.detail
    return text?.trim() || undefined
}

export type HandoffFailureReason =
    | 'not_signed_in'
    | 'run_not_started'
    | 'network'
    | 'free_trial'
    | 'pr_limit'
    | 'task_limit'
    | 'busy'
    | 'start_timeout'
    | 'forbidden'
    | 'not_found'
    | 'unknown'

/** One reason per row of the error copy table, so the copy and the tracked reason cannot disagree. */
export function handoffFailureReason(error: unknown): HandoffFailureReason {
    if (error instanceof NotSignedInError) {
        return 'not_signed_in'
    }
    if (error instanceof RunNotStartedError) {
        return 'run_not_started'
    }
    if (!(error instanceof ApiError)) {
        return 'network'
    }
    if (error.code === 'self_driving_free_trial') {
        return 'free_trial'
    }
    if (error.status === 402) {
        return 'pr_limit'
    }
    if (error.code === 'signal_report_task_cap' || error.code === 'throttled') {
        return 'task_limit'
    }
    if (error.status === 429) {
        return 'busy'
    }
    if (error.code === 'warm_run_activation_unavailable') {
        return 'start_timeout'
    }
    if (error.status === 403) {
        return 'forbidden'
    }
    if (error.status === 404) {
        return 'not_found'
    }
    return 'unknown'
}

export function handoffErrorMessage(error: unknown): string {
    const server = error instanceof ApiError ? serverCopy(error) : undefined
    switch (handoffFailureReason(error)) {
        case 'not_signed_in':
            return 'Sign in again to hand off this report.'
        case 'run_not_started':
            return (error as RunNotStartedError).message
        case 'network':
            return "Couldn't reach PostHog. Check your connection and try again."
        case 'free_trial':
            return server ?? FREE_TRIAL_COPY
        case 'pr_limit':
            return server ?? PR_LIMIT_COPY
        case 'task_limit':
            return server ?? TASK_LIMIT_COPY
        case 'busy':
            return server ?? 'PostHog is busy. Try again in a few minutes.'
        case 'start_timeout':
            return "PostHog couldn't start the agent in time. Try again."
        case 'forbidden':
            return server ?? "You don't have access to hand off reports in this project."
        case 'not_found':
            return 'This report is no longer available.'
        case 'unknown':
            return "Couldn't hand off to PostHog. Try again."
    }
}
