import type { ActionBarState, DecisionAnswer, ReportView, WorkView } from '@/model/types'

import { actionBarStateFor } from './actionBarState'
import type { ReportHandoff, StoredAnswer } from './handoffStore'
import { currentDecision, mergeLiveRun, runTarget, visibleAnswer } from './liveReport'
import { parsePermissionRequest, requestKind } from './permissionRequest'
import { initialRunState } from './runStream'
import type { RunStreamState } from './types'

const PR_URL = 'https://github.com/org/repo/pull/42'

function report(work: WorkView = { state: 'unclaimed' }): ReportView {
    return {
        id: 'rep-1',
        title: 'Legend crash',
        webUrl: 'https://app.example.com/project/2/inbox/reports/rep-1',
        sourceProduct: 'error_tracking',
        sourceLabel: 'Error',
        accent: 'alert',
        headline: { rest: 'Headline' },
        lede: '',
        evidence: [],
        owner: { kind: 'none' },
        facts: [],
        supportingMetrics: [],
        charts: [],
        signals: [],
        activity: [],
        work,
        task: { taskId: 'task-1', runId: 'run-1', status: 'in_progress' },
        reviewers: [],
        prompt: 'placeholder',
        contextNote: '',
    }
}

function live(extra: Partial<RunStreamState> = {}): RunStreamState {
    return { ...initialRunState('task-1', 'run-1', 'in_progress'), ...extra }
}

const QUESTION = (() => {
    const record = parsePermissionRequest({
        requestId: 'req-q',
        options: [{ optionId: 'option_0', kind: 'allow_once', name: 'SDK' }],
        toolCall: {
            toolCallId: 'tc',
            _meta: { codeToolKind: 'question', questions: [{ question: 'Which fix?', options: [{ label: 'SDK' }] }] },
        },
    })
    if (!record) {
        throw new Error('fixture did not parse')
    }
    return { record, kind: requestKind(record), replayed: false }
})()

const ANSWERED: StoredAnswer = {
    questionId: 'req-q',
    question: { id: 'req-q', question: 'Which fix?', options: [{ id: 'option_0', title: 'SDK' }] },
    optionId: 'option_0',
    text: 'SDK',
    delivery: 'delivered',
    activity: 3,
}

function footer(base: ReportView, entry: ReportHandoff): ActionBarState {
    const merged = mergeLiveRun(base, entry)
    const stored = visibleAnswer(entry, currentDecision(entry))
    const answer: DecisionAnswer | undefined = stored ? { questionId: stored.questionId, text: stored.text } : undefined
    return actionBarStateFor(merged, { answer })
}

describe('liveReport', () => {
    test('an ended turn stays idle with a draft PR through another turn', () => {
        const pr = { url: PR_URL, state: 'draft' as const }
        const base = report({ state: 'in_review', pullRequest: pr })
        for (const state of [live({ turnEnded: true }), live({ phase: 'working' }), live({ turnEnded: true })]) {
            const output = footer(base, { refresh: 0, live: state })
            expect(output.pullRequests).toEqual([pr])
            expect(output.request).toBeUndefined()
            expect(output.showHandoff).toBe(false)
        }
    })

    test('a real question and its answer coexist with all PRs', () => {
        const second = 'https://github.com/example/app/pull/43'
        const base = report({ state: 'in_review', pullRequest: { url: PR_URL, state: 'merged' } })
        const entry = { refresh: 0, live: live({ pending: QUESTION, prUrls: [`${PR_URL}/`, second], activity: 3 }) }
        expect(footer(base, entry)).toMatchObject({
            request: ANSWERED.question,
            pullRequests: [{ state: 'merged' }, { state: 'unknown' }],
        })
        const answered = footer(base, { ...entry, answer: ANSWERED })
        expect(answered.request).toBeUndefined()
        expect(answered.answer).toMatchObject({ text: 'SDK' })
        expect(answered.pullRequests).toHaveLength(2)
    })

    test('a new local task wins historical work until the canonical claim catches up', () => {
        const started = { taskId: 'new-task', runId: 'new-run' }
        expect(runTarget(report(), { refresh: 0, started })).toEqual(started)
        const claimed = report({ state: 'working', assignee: { kind: 'task', name: 'PostHog', taskId: 'task-1' } })
        expect(runTarget(claimed, { refresh: 0, started })).toEqual({ taskId: 'task-1', runId: 'run-1' })
    })

    test('canonical claims supersede optimistic or historical tasks', () => {
        const started = { taskId: 'task-old', runId: 'run-old' }
        const external = report({ state: 'working', assignee: { kind: 'agent', name: 'Codex' } })
        const entry = { refresh: 0, started, live: live({ phase: 'working', pending: QUESTION }) }
        expect(runTarget(external, entry)).toBeUndefined()
        expect(mergeLiveRun(external, entry).task).toBeUndefined()
        const canonical = report({ state: 'working', assignee: { kind: 'task', name: 'PostHog', taskId: 'task-1' } })
        expect(runTarget(canonical, entry)).toEqual({ taskId: 'task-1', runId: 'run-1' })
    })

    test('canonical terminal status wins over a stale live state for the same run', () => {
        const base = { ...report(), task: { taskId: 'task-1', runId: 'run-1', status: 'completed' as const } }
        const merged = mergeLiveRun(base, {
            refresh: 0,
            live: live({ phase: 'working', pending: QUESTION, prUrls: [PR_URL] }),
        })
        expect(merged.task).toMatchObject({ status: 'completed', phase: 'idle', pendingDecision: undefined })
        expect(merged.work.pullRequests).toHaveLength(1)
    })

    test('an older run cannot change a newer task status or request', () => {
        const base = { ...report(), task: { taskId: 'task-1', runId: 'run-2', status: 'completed' as const } }
        const merged = mergeLiveRun(base, {
            refresh: 0,
            live: live({ phase: 'working', pending: QUESTION, prUrls: [PR_URL] }),
        })
        expect(merged.task).toEqual(base.task)
        expect(merged.work.pullRequests).toEqual([])
    })

    test('canonical PR state survives normalized streamed URLs and more PRs', () => {
        const merged = mergeLiveRun(report({ state: 'done', pullRequest: { url: PR_URL, state: 'merged' } }), {
            refresh: 0,
            live: live({
                status: 'failed',
                errorMessage: 'Sandbox crashed',
                prUrls: [`${PR_URL}/?tab=checks`, 'https://github.com/example/app/pull/43'],
                prUrl: 'https://github.com/example/app/pull/44',
            }),
        })
        expect(merged.work.pullRequest).toEqual({ url: PR_URL, state: 'merged' })
        expect(merged.work.pullRequests).toEqual([
            { url: PR_URL, state: 'merged' },
            { url: 'https://github.com/example/app/pull/43', state: 'unknown', number: 43 },
            { url: 'https://github.com/example/app/pull/44', state: 'unknown', number: 44 },
        ])
        expect(merged.task).toMatchObject({ status: 'failed', errorMessage: 'Sandbox crashed' })
    })

    test('new activity clears the delivered answer without manufacturing another request', () => {
        expect(
            footer(report(), { refresh: 0, live: live({ activity: 4, turnEnded: true }), answer: ANSWERED }).answer
        ).toBeUndefined()
        expect(currentDecision({ refresh: 0, live: live({ turnEnded: true }) })).toBeUndefined()
    })
})
