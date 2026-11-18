import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { mockTask } from '../../__mocks__/inboxMocks'
import { INBOX_EVENTS } from '../../inboxAnalytics'
import type { ReportTaskEntry } from '../../logics/inboxReportDetailLogic'
import { ReportTaskRow } from './ReportTaskRow'

jest.mock('posthog-js')

const summary = 'Rejected the blank recipient in the serializer.\nBranch: inbox/fix-invites — PR #12001.'

function entry(taskSummary: string | null): ReportTaskEntry {
    const task = mockTask('impl-task', 'completed')
    return {
        task: { ...task, latest_run: { ...task.latest_run, task_summary: taskSummary } },
        purpose: 'implementation',
        purposeLabel: 'Implementation',
        startedAt: '2026-09-20T09:00:00Z',
    }
}

function summaryCaptures(): Record<string, unknown>[] {
    return (posthog.capture as jest.Mock).mock.calls
        .filter(([event]) => event === INBOX_EVENTS.RUN_SUMMARY_VIEWED)
        .map(([, properties]) => properties)
}

describe('ReportTaskRow', () => {
    beforeEach(() => {
        initKeaTests()
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    test.each([
        ['a hover', async (row: HTMLElement) => await userEvent.hover(row)],
        [
            'keyboard focus',
            async (row: HTMLElement) => {
                await userEvent.tab()
                expect(row).toHaveFocus()
            },
        ],
    ])('reveals the run summary on %s, and records the read', async (_case, reveal) => {
        render(<ReportTaskRow entry={entry(summary)} expanded={false} onToggle={() => undefined} />)

        expect(screen.queryByText(/Rejected the blank recipient/)).not.toBeInTheDocument()

        await reveal(screen.getByRole('button'))

        expect(screen.getByTestId('report-run-summary')).toHaveTextContent('Implementation')
        expect(await screen.findByText(/Rejected the blank recipient/)).toHaveTextContent('PR #12001')
        expect(summaryCaptures()).toEqual([
            expect.objectContaining({
                inbox_client: 'cloud',
                run_purpose: 'implementation',
                run_status: 'completed',
                summary_length: summary.length,
            }),
        ])
    })

    // A run that wrote no summary must not offer the hint or send a read — an empty tooltip reads as
    // a broken row, and a read with nothing behind it makes the event useless as a measure.
    it('leaves a run with no summary alone', async () => {
        render(<ReportTaskRow entry={entry(null)} expanded={false} onToggle={() => undefined} />)

        await userEvent.hover(screen.getByRole('button'))

        expect(screen.getByText('Implementation')).toBeInTheDocument()
        expect(screen.queryByTestId('report-run-summary')).not.toBeInTheDocument()
        expect(summaryCaptures()).toEqual([])
    })
})
