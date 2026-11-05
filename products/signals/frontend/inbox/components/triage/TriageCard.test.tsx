/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inboxTriageLogic } from '../../logics/inboxTriageLogic'
import { reportGithubAccessLogic } from '../../logics/reportGithubAccessLogic'
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
                '/api/projects/:team_id/signals/onboarding/': { draft: null, completed_at: null },
                '/api/projects/:team_id/signals/scout/configs/': [],
            },
        })
        initKeaTests()
        logic = inboxTriageLogic()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('keeps Unassign me on the next report while the command key stays held', () => {
        logic.mount()
        const { rerender } = render(<TriageCard report={makeReport('r-1')} expanded={false} />)
        fireEvent.keyDown(window, { key: 'Control' })
        expect(screen.getByText('Unassign me')).toBeInTheDocument()

        rerender(<TriageCard report={makeReport('r-2')} expanded={false} />)

        expect(screen.getByText('Unassign me')).toBeInTheDocument()
        expect(screen.queryByText('Dismiss')).not.toBeInTheDocument()
    })

    it.each([
        [503, 'button'],
        [200, 'button'],
        [200, 'keyboard'],
    ] as const)('recovers GitHub access without leaving triage (status %i, %s)', async (status, entrypoint) => {
        const report = { ...makeReport('r-1'), actionability: 'immediately_actionable' as const }
        let repositoryStatus = status
        let available = false
        const loadReportDetails = jest.fn(() => ({ results: [], count: 0 }))
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': { results: [report], next: null, count: 1 },
                '/api/projects/:team_id/signals/reports/:report_id/artefacts/': loadReportDetails,
                '/api/projects/:team_id/signals/onboarding/': {
                    draft: null,
                    completed_at: null,
                    github_optional_available: true,
                },
                '/api/projects/:team_id/integrations/': { results: [{ id: 1, kind: 'github' }], next: null },
                '/api/projects/:team_id/integrations/github/available_installations/': {
                    installations: [],
                    personal_github_connected: false,
                },
                '/api/projects/:team_id/integrations/1/github_repository_access/': () => [
                    repositoryStatus,
                    { available },
                ],
            },
        })
        logic.mount()
        render(<TriageCard report={report} expanded={false} />)
        const access = reportGithubAccessLogic({ report, surface: 'triage_mode' })
        await waitFor(() => expect(access.values[status === 503 ? 'failed' : 'repairNeeded']).toBe(true))
        if (entrypoint === 'keyboard') {
            logic.actions.createPrForCurrent()
        } else {
            fireEvent.click(screen.getByText('Implement').closest('button')!)
            expect(screen.getByText('Copy prompt for your agent')).toBeInTheDocument()
            if (status === 200) {
                fireEvent.click(screen.getByText('Implement with PostHog').closest('button')!)
            }
        }
        if (status === 200) {
            expect(await screen.findByText('Manage on GitHub')).toBeInTheDocument()
        }
        const retry = (await screen.findByText(status === 503 ? 'Retry GitHub check' : 'Check access again')).closest(
            'button'
        )!
        repositoryStatus = 200
        available = true
        fireEvent.click(retry)
        expect(retry).toHaveAttribute('aria-disabled', 'true')
        await waitFor(() =>
            expect(reportGithubAccessLogic({ report, surface: 'triage_mode' }).values.disabledReason).toBeNull()
        )
        expect(screen.queryByText('Retry GitHub check')).not.toBeInTheDocument()
        expect(screen.getByText('Implement')).toBeInTheDocument()
        expect(loadReportDetails).not.toHaveBeenCalled()
    })
})
