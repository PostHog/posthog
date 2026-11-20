/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ReportPageApi } from 'products/today/frontend/generated/api.schemas'

import { inboxTriageLogic } from '../../logics/inboxTriageLogic'
import { reportGithubAccessLogic } from '../../logics/reportGithubAccessLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { QuillTriageCard } from './QuillTriageCard'

const PAGE: ReportPageApi = {
    lead: '',
    proposal: '',
    impact_sentence: '',
    named_pull_request: null,
    solution_names_pull_request: false,
    evidence: [],
    source_count: 0,
    impact_numbers: [],
    last_seen: null,
}

function makeReport(repoSlug: string | null): SignalReport {
    return {
        id: 'r-1',
        title: 'Report r-1',
        summary: 'Checkout fails for Safari users.',
        status: SignalReportStatus.READY,
        actionability: 'immediately_actionable',
        total_weight: 0,
        signal_count: 1,
        artefact_count: 0,
        is_suggested_reviewer: true,
        priority: 'P2',
        source_products: ['error_tracking'],
        repo_slug: repoSlug,
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
    } satisfies SignalReport
}

describe('QuillTriageCard', () => {
    let logic: ReturnType<typeof inboxTriageLogic.build>

    function mockReport(
        report: SignalReport,
        { accessStatus = 200, pageStatus = 200 }: { accessStatus?: number; pageStatus?: number | (() => number) } = {}
    ): void {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                '/api/projects/:team_id/signals/reports/': { results: [report], next: null, count: 1 },
                '/api/projects/:team_id/signals/reports/:id/': report,
                '/api/projects/:team_id/today/reports/:id/page/': () => [
                    typeof pageStatus === 'function' ? pageStatus() : pageStatus,
                    PAGE,
                ],
                '/api/projects/:team_id/signals/scout/configs/': [],
                '/api/projects/:team_id/today/pulse_pins/': { pins: [], hidden: [] },
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
                    accessStatus,
                    { available: false },
                ],
            },
        })
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    it.each([
        ['a failed access check', 'example/app', 503, false, 'Retry GitHub check'],
        ['missing access, from the keyboard', 'example/app', 200, true, 'Check access again'],
        ['a report without a repository', null, 200, false, 'Select a repository to implement this report'],
    ])('offers recovery for %s', async (_name, repoSlug, accessStatus, pressCreatePr, recoveryText) => {
        const report = makeReport(repoSlug)
        mockReport(report, { accessStatus })
        logic = inboxTriageLogic()
        logic.mount()
        await waitFor(() => expect(logic.values.currentReport?.id).toBe(report.id))
        render(<QuillTriageCard report={report} expanded={false} />)
        const access = reportGithubAccessLogic({ report, surface: 'triage_mode' })
        await waitFor(() => expect(access.values.loading).toBe(false))

        if (pressCreatePr) {
            logic.actions.createPrForCurrent()
        }

        expect(await screen.findByText(recoveryText)).toBeInTheDocument()
    })

    it('keeps the summary and offers a retry when the report page fails to load', async () => {
        let pageStatus = 500
        const report = makeReport('example/app')
        mockReport(report, { pageStatus: () => pageStatus })
        logic = inboxTriageLogic()
        logic.mount()
        render(<QuillTriageCard report={report} expanded={false} />)

        const retry = (await screen.findByText('Try again')).closest('button')!
        expect(screen.getByText('Checkout fails for Safari users.')).toBeInTheDocument()
        pageStatus = 200
        fireEvent.click(retry)

        await waitFor(() => expect(screen.queryByText('Try again')).not.toBeInTheDocument())
    })
})
