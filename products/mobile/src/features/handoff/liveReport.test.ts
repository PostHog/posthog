import type { ActionBarState, DecisionAnswer, ReportView, WorkView } from '@/model/types'

import { actionBarStateFor } from './actionBarState'
import type { ReportHandoff, StoredAnswer } from './handoffStore'
import { currentDecision, mergeLiveRun, visibleAnswer } from './liveReport'
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
        facts: [],
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
    const stored = visibleAnswer(entry, currentDecision(entry, false))
    const answer: DecisionAnswer | undefined = stored ? { questionId: stored.questionId, text: stored.text } : undefined
    return actionBarStateFor(merged, { answer })
}

describe('liveReport', () => {
    test.each<[string, ReportView, ReportHandoff, ActionBarState]>([
        [
            'a run started here shows as handed before the report knows it',
            { ...report(), task: undefined },
            { refresh: 0, started: { taskId: 'task-2', runId: 'run-2' } },
            'handed',
        ],
        [
            'a pending question asks for a decision',
            report(),
            { refresh: 0, live: live({ pending: QUESTION }) },
            'decision',
        ],
        [
            'a delivered answer stays until the run shows new activity',
            report(),
            { refresh: 0, live: live({ activity: 3 }), answer: ANSWERED },
            'decided',
        ],
        [
            'the run moving on clears the delivered answer',
            report(),
            { refresh: 0, live: live({ activity: 4 }), answer: ANSWERED },
            'handed',
        ],
        [
            'a PR the stream reports is ready to review',
            report(),
            { refresh: 0, live: live({ prUrl: PR_URL, prUrls: [PR_URL] }) },
            'pr_ready',
        ],
        [
            'the report still wins on a PR it knows was merged',
            report({ state: 'in_review', pullRequest: { url: PR_URL, state: 'merged' } }),
            { refresh: 0, live: live({ status: 'completed', prUrl: PR_URL, prUrls: [PR_URL] }) },
            'idle',
        ],
        [
            'an ended turn without a PR waits for a reply',
            report(),
            { refresh: 0, live: live({ turnEnded: true, lastMessage: 'Should I also patch the API?' }) },
            'decision',
        ],
        [
            'an ended turn with an open PR shows the PR',
            report(),
            {
                refresh: 0,
                live: live({ turnEnded: true, lastMessage: 'Opened the PR.', prUrl: PR_URL, prUrls: [PR_URL] }),
            },
            'pr_ready',
        ],
        ['a failed run offers the hand-off again', report(), { refresh: 0, live: live({ status: 'failed' }) }, 'idle'],
    ])('%s', (_name, base, entry, expected) => {
        expect(footer(base, entry)).toBe(expected)
    })

    test('the live overlay fills the PR number and the error', () => {
        const merged = mergeLiveRun(report(), {
            refresh: 0,
            live: live({ status: 'failed', errorMessage: 'Sandbox crashed', prUrl: PR_URL, prUrls: [PR_URL] }),
        })
        expect(merged.work.pullRequest).toEqual({ url: PR_URL, state: 'open', number: 42 })
        expect(merged.task).toMatchObject({ status: 'failed', errorMessage: 'Sandbox crashed' })
    })
})
