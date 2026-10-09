import { ApiError, NotSignedInError } from '@/api/client'
import { fetchReport } from '@/api/reports'
import { createTask, startTaskRun } from '@/api/tasks'
import { isRecord } from '@/lib/records'

import { type Clock, realClock } from './clock'
import { buildCreatePrReportPrompt } from './prompt'

/** The model a hand-off runs on. The app has no model picker, so it sends what the web falls back to. */
const HANDOFF_RUNTIME = { runtime_adapter: 'claude', model: 'claude-opus-5-5', reasoning_effort: 'high' } as const

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

// Makes the same two calls as the web's Create PR. The prompt reads the report fresh so it matches what the web sends.
export async function kickOffReportTask(
    reportId: string,
    options: { signal?: AbortSignal; clock?: Clock } = {}
): Promise<KickoffResult> {
    const report = await fetchReport(reportId, options.signal)
    const prompt = buildCreatePrReportPrompt(report)
    const task = await withWarmRetry(
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
                        ...HANDOFF_RUNTIME,
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

export function handoffErrorMessage(error: unknown): string {
    if (error instanceof NotSignedInError) {
        return 'Sign in again to hand off this report.'
    }
    if (error instanceof RunNotStartedError) {
        return error.message
    }
    if (!(error instanceof ApiError)) {
        return "Couldn't reach PostHog. Check your connection and try again."
    }
    if (error.code === 'self_driving_free_trial') {
        return serverCopy(error) ?? FREE_TRIAL_COPY
    }
    if (error.status === 402) {
        return serverCopy(error) ?? PR_LIMIT_COPY
    }
    if (error.code === 'signal_report_task_cap' || error.code === 'throttled') {
        return serverCopy(error) ?? TASK_LIMIT_COPY
    }
    if (error.status === 429) {
        return serverCopy(error) ?? 'PostHog is busy. Try again in a few minutes.'
    }
    if (error.code === 'warm_run_activation_unavailable') {
        return "PostHog couldn't start the agent in time. Try again."
    }
    if (error.status === 403) {
        return serverCopy(error) ?? "You don't have access to hand off reports in this project."
    }
    if (error.status === 404) {
        return 'This report is no longer available.'
    }
    return "Couldn't hand off to PostHog. Try again."
}
