import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { type SignalReport, SignalReportStatus } from '../../types'
import { InboxBulkSelectionBar } from './InboxBulkSelectionBar'

function makeReport(id: string, overrides: Partial<SignalReport> = {}): SignalReport {
    return {
        id,
        title: `Report ${id}`,
        summary: 'summary',
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        relevant_user_count: null,
        artefact_count: 0,
        is_suggested_reviewer: false,
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
        ...overrides,
    }
}

describe('InboxBulkSelectionBar', () => {
    let logic: ReturnType<typeof inboxBulkActionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = inboxBulkActionsLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    // The bar holds a count and no titles, so its dialogs have to count reports at every size. The
    // single-report copy would print the "Untitled report" placeholder over a report that has a title.
    it.each([
        { button: 'Dismiss', reportIds: ['a'], heading: 'Dismiss 1 report?' },
        { button: 'Dismiss', reportIds: ['a', 'b'], heading: 'Dismiss 2 reports?' },
        { button: 'Resolve', reportIds: ['a'], heading: 'Resolve 1 report?' },
        { button: 'Resolve', reportIds: ['a', 'b'], heading: 'Resolve 2 reports?' },
    ])(
        '$button counts the selection in its dialog at $reportIds.length selected',
        async ({ button, reportIds, heading }) => {
            logic.actions.setSelectedReportIds(reportIds)
            render(<InboxBulkSelectionBar reports={reportIds.map((id) => makeReport(id))} />)

            fireEvent.click(screen.getByText(button))

            expect(await screen.findByText(heading)).toBeInTheDocument()
        }
    )

    it('warns when bulk dismissal closes a selected pull request', async () => {
        logic.actions.setSelectedReportIds(['a'])
        render(
            <InboxBulkSelectionBar
                reports={[makeReport('a', { implementation_pr_url: 'https://github.com/PostHog/posthog/pull/1' })]}
            />
        )

        fireEvent.click(screen.getByText('Dismiss'))

        expect(await screen.findByText(/The pull request opened for this report is closed/)).toBeInTheDocument()
    })
})
