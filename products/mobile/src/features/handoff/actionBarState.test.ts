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
        owner: { kind: 'none' },
        facts: [],
        supportingMetrics: [],
        charts: [],
        signals: [],
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
    test.each<[string, ReportView, ActionBarLocalState, Partial<ActionBarState>]>([
        ['unclaimed actionable report', report({ state: 'unclaimed' }), {}, { showHandoff: true }],
        [
            'queued task',
            report({ state: 'working' }, run('queued')),
            {},
            { showHandoff: false, activity: { title: 'PostHog queued', tone: 'idle' } },
        ],
        [
            'unknown active turn',
            report({ state: 'working' }, run('in_progress')),
            {},
            { showHandoff: false, activity: { title: 'PostHog activity unavailable', tone: 'idle' } },
        ],
        [
            'idle task retains the chat',
            report({ state: 'working' }, run('in_progress', { phase: 'idle' })),
            {},
            { showHandoff: false, activity: { title: 'PostHog finished this turn', tone: 'idle' } },
        ],
        [
            'failed task retains the chat',
            report({ state: 'working' }, run('failed')),
            {},
            { showHandoff: false, activity: { title: 'PostHog run failed', tone: 'stopped' } },
        ],
        [
            'external claim',
            report(
                { state: 'working', assignee: { kind: 'agent', name: 'Codex' } },
                run('in_progress', { phase: 'working', pendingDecision: QUESTION })
            ),
            {},
            {
                showHandoff: false,
                activity: { title: 'Claimed by Codex', meta: 'Live activity unavailable', tone: 'idle' },
            },
        ],
        [
            'question remains alongside a draft PR',
            report(
                { state: 'in_review', pullRequest: { ...OPEN_PR, state: 'draft' } },
                run('in_progress', { pendingDecision: QUESTION })
            ),
            {},
            { showHandoff: false, request: QUESTION },
        ],
        [
            'answer stays alongside a PR',
            report({ state: 'in_review', pullRequest: OPEN_PR }, run('in_progress', { pendingDecision: QUESTION })),
            { answer: { questionId: 'q1', text: 'Guard it' } },
            { showHandoff: false, answer: { questionId: 'q1', text: 'Guard it' } },
        ],
    ])('%s', (_name, input, local, expected) => {
        expect(actionBarStateFor(input, local)).toMatchObject(expected)
    })

    test.each(['open', 'draft', 'merged', 'closed', 'unknown'] as const)(
        'a %s PR remains visible after resolution',
        (state) => {
            const pr = { ...OPEN_PR, state }
            const output = actionBarStateFor(report({ state: 'done', pullRequest: pr }, run('failed')))
            expect(output.pullRequests).toEqual([pr])
            expect(output.showHandoff).toBe(false)
            expect(output.activity?.tone).toBe('stopped')
        }
    )

    test('terminal runs do not ask a stale question', () => {
        expect(
            actionBarStateFor(report({ state: 'working' }, run('failed', { pendingDecision: QUESTION }))).request
        ).toBeUndefined()
    })

    test('an answered question stops asking for an answer', () => {
        const output = actionBarStateFor(
            report({ state: 'working' }, run('in_progress', { pendingDecision: QUESTION })),
            { answer: { questionId: 'q1', text: 'Guard it' } }
        )
        expect(output.request).toBeUndefined()
        expect(output.activity?.title).not.toContain('waiting for your answer')
    })

    test('an unavailable connection does not claim old activity is live', () => {
        const output = actionBarStateFor(
            report(
                { state: 'working' },
                run('in_progress', { phase: 'working', stage: 'Editing a.ts', connection: 'unavailable' })
            )
        )
        expect(output.activity).toEqual({ title: 'PostHog activity unavailable', tone: 'idle' })
    })

    test('failed bootstrap reports unavailable activity instead of starting forever', () => {
        const output = actionBarStateFor(
            report({ state: 'working' }, run('not_started', { phase: 'unknown', connection: 'unavailable' }))
        )
        expect(output.activity).toEqual({ title: 'PostHog activity unavailable', tone: 'idle' })
    })

    test('a report that cannot act does not offer a handoff', () => {
        expect(actionBarStateFor({ ...report({ state: 'unclaimed' }), canAct: false }).showHandoff).toBe(false)
    })
})
