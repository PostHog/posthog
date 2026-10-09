import type { ActionBarLocalState, ActionBarState, ReportView, TaskRunView, WorkView } from '@/model/types'

import { actionBarStateFor } from './actionBarState'

const QUESTION = { id: 'q1', question: 'Which fix?', options: [{ id: 'a', title: 'Guard it' }] }
const OPEN_PR = { url: 'https://github.com/example/app/pull/1', state: 'open' as const }

function report(work: WorkView, task?: TaskRunView): ReportView {
    return {
        id: 'r1',
        title: 'Title',
        sourceProduct: 'error_tracking',
        sourceLabel: 'Error',
        accent: 'alert',
        headline: { rest: 'Headline' },
        lede: '',
        evidence: [],
        facts: [],
        activity: [],
        work,
        ...(task ? { task } : {}),
        reviewers: [],
        prompt: '',
        contextNote: '',
    }
}

const run = (status: TaskRunView['status'], extra: Partial<TaskRunView> = {}): TaskRunView => ({
    taskId: 't1',
    runId: 'run1',
    status,
    ...extra,
})

describe('actionBarStateFor', () => {
    test.each<[string, ReportView, ActionBarLocalState, ActionBarState]>([
        ['nothing happening', report({ state: 'unclaimed' }), {}, 'idle'],
        [
            'done beats a pending question',
            report({ state: 'done' }, run('in_progress', { pendingDecision: QUESTION })),
            {},
            'resolved',
        ],
        [
            'unanswered question',
            report({ state: 'working' }, run('in_progress', { pendingDecision: QUESTION })),
            {},
            'decision',
        ],
        [
            'unanswered question beats an open PR',
            report({ state: 'in_review', pullRequest: OPEN_PR }, run('in_progress', { pendingDecision: QUESTION })),
            {},
            'decision',
        ],
        [
            'answered question',
            report({ state: 'working' }, run('in_progress', { pendingDecision: QUESTION })),
            { answer: { questionId: 'q1', text: 'Guard it' } },
            'decided',
        ],
        [
            'answer to an older question does not hide a new one',
            report({ state: 'working' }, run('in_progress', { pendingDecision: QUESTION })),
            { answer: { questionId: 'q0', text: 'Old' } },
            'decision',
        ],
        [
            'open PR beats an answered question',
            report({ state: 'in_review', pullRequest: OPEN_PR }, run('in_progress', { pendingDecision: QUESTION })),
            { answer: { questionId: 'q1', text: 'Guard it' } },
            'pr_ready',
        ],
        ['open PR', report({ state: 'in_review', pullRequest: OPEN_PR }, run('completed')), {}, 'pr_ready'],
        [
            'merged PR is not ready for review',
            report({ state: 'in_review', pullRequest: { ...OPEN_PR, state: 'merged' } }),
            {},
            'idle',
        ],
        ['queued run', report({ state: 'unclaimed' }, run('queued')), {}, 'handed'],
        ['failed run offers the hand-off again', report({ state: 'unclaimed' }, run('failed')), {}, 'idle'],
        [
            'failed run with a claim it never released offers the hand-off again',
            report({ state: 'working', assignee: { kind: 'task', name: 'PostHog' } }, run('failed')),
            {},
            'idle',
        ],
        [
            'agent claim without a run',
            report({ state: 'working', assignee: { kind: 'agent', name: 'PostHog' } }),
            {},
            'handed',
        ],
        [
            'a person working on it still offers the hand-off',
            report({ state: 'working', assignee: { kind: 'user', name: 'Sana' } }),
            {},
            'idle',
        ],
        ['hand-off in flight', report({ state: 'unclaimed' }), { handOffPending: true }, 'handed'],
    ])('%s', (_name, input, local, expected) => {
        expect(actionBarStateFor(input, local)).toBe(expected)
    })
})
