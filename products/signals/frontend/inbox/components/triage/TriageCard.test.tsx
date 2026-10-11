/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inboxTriageLogic } from '../../logics/inboxTriageLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { TriageCard } from './InboxTriageView'

jest.mock('lib/components/TZLabel', () => ({
    TZLabel: ({ time }: { time: string }) => <span>{time}</span>,
}))

function makeReport(id: string): SignalReport {
    return {
        id,
        title: `Report ${id}`,
        summary: 'summary',
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        artefact_count: 0,
        is_suggested_reviewer: true,
        priority: 'P2',
        source_products: ['error_tracking'],
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
    } satisfies SignalReport
}

describe('TriageCard', () => {
    let logic: ReturnType<typeof inboxTriageLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                '/api/projects/:team_id/signals/reports/': { count: 0, next: null, previous: null, results: [] },
            },
        })
        initKeaTests()
        logic = inboxTriageLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('keeps Unassign me on the next report while the command key stays held', () => {
        const { rerender } = render(<TriageCard report={makeReport('r-1')} expanded={false} />)
        fireEvent.keyDown(window, { key: 'Control' })
        expect(screen.getByText('Unassign me')).toBeInTheDocument()

        rerender(<TriageCard report={makeReport('r-2')} expanded={false} />)

        expect(screen.getByText('Unassign me')).toBeInTheDocument()
        expect(screen.queryByText('Dismiss')).not.toBeInTheDocument()
    })
})
