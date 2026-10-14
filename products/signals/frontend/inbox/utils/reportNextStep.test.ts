import { makeReport, mockTask } from '../__mocks__/inboxMocks'
import type { ReportTaskEntry } from '../logics/inboxReportDetailLogic'
import { SignalReport, SignalReportStatus } from '../types'
import { reportNextStep } from './reportNextStep'

describe('reportNextStep', () => {
    const ready = makeReport({
        status: SignalReportStatus.READY,
        actionability: 'immediately_actionable',
        pull_requests: undefined,
    })

    it.each<[Partial<SignalReport>, string]>([
        [{}, 'implement'],
        [{ status: SignalReportStatus.PENDING_INPUT }, 'investigate'],
        [{ actionability: 'requires_human_input' }, 'investigate'],
        [{ status: SignalReportStatus.FAILED }, 'investigate'],
        [{ actionability: 'not_actionable' }, 'none'],
        [{ status: SignalReportStatus.RESOLVED }, 'none'],
        [{ status: SignalReportStatus.SUPPRESSED }, 'none'],
        [{ status: SignalReportStatus.IN_PROGRESS }, 'wait'],
        [{ already_addressed: true }, 'wait'],
        [{ implementation_pr_url: 'https://github.com/example/app/pull/1', implementation_pr_state: 'open' }, 'review'],
        [{ implementation_pr_url: 'https://github.com/example/app/pull/1', implementation_pr_state: 'merged' }, 'wait'],
        [
            { implementation_pr_url: 'https://github.com/example/app/pull/1', implementation_pr_state: 'closed' },
            'investigate',
        ],
        [
            { implementation_pr_url: 'https://untrusted.example/app/pull/1', implementation_pr_state: 'open' },
            'investigate',
        ],
    ])('selects the next action for %j', (overrides, kind) => {
        expect(reportNextStep({ ...ready, ...overrides }, [], null).kind).toBe(kind)
    })

    it('waits for task data and honors an implementation claim', () => {
        expect(reportNextStep(ready, null, null).kind).toBe('load')
        expect(reportNextStep(ready, [], 'shipped_pr').kind).toBe('wait')
    })

    it('reviews the selected open PR when a report has several PRs', () => {
        const first = makeReport({
            implementation_pr_url: 'https://github.com/example/app/pull/1',
            implementation_pr_state: 'open',
        }).pull_requests![0]
        const second = { ...first, id: 'pr-2', url: 'https://github.com/example/app/pull/2' }
        expect(reportNextStep({ ...ready, pull_requests: [first, second] }, [], null, second.url)).toMatchObject({
            kind: 'review',
            url: second.url,
        })
    })

    it.each(['research', 'implementation', 'other'] as const)('continues a running %s task', (purpose) => {
        const task = mockTask('task-1', 'in_progress')
        const entry = { task, purpose, purposeLabel: purpose, startedAt: ready.created_at } as ReportTaskEntry
        expect(reportNextStep(ready, [entry], null)).toMatchObject({
            kind: 'task',
            taskId: task.id,
            runId: task.latest_run!.id,
        })
    })
})
