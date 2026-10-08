import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { reportMetricsFixture } from '../../__mocks__/reportMetricMocks'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { ReportExpectedImpact } from './ReportExpectedImpact'

jest.mock('./ReportCheckMetricChart', () => ({ ReportCheckMetricChart: () => <div>Chart</div> }))

const report: SignalReport = {
    id: 'report-1',
    title: 'Checkout errors',
    summary: 'Checkout sometimes fails.',
    status: SignalReportStatus.READY,
    total_weight: 0,
    signal_count: 1,
    artefact_count: 0,
    is_suggested_reviewer: false,
    metrics: [{ ...reportMetricsFixture[0], title: 'Failed checkouts', goal_value: 999 }],
    created_at: '2026-09-29T00:00:00Z',
    updated_at: '2026-09-29T00:00:00Z',
}

const check: SignalReportCheckApi = {
    id: 'check-1',
    title: 'Checkout errors stay below 5',
    rationale: 'The fix should reduce failures.',
    kind: 'metric_threshold',
    status: 'pending',
    config: {
        metric_id: reportMetricsFixture[0].metric_id,
        query: reportMetricsFixture[0].query as Record<string, unknown>,
        comparison: { operator: 'lte', value: 5 },
        baseline_value: 20,
        metric_kind: reportMetricsFixture[0].kind,
        value_format: reportMetricsFixture[0].value_format,
        unit: reportMetricsFixture[0].unit,
    },
    approved_at: null,
    next_run_at: '2026-10-13T00:00:00Z',
    soak_minutes: 20160,
    run_interval_minutes: null,
    runs_remaining: 1,
    expires_at: '2026-11-13T00:00:00Z',
    last_run_at: null,
    last_outcome: null,
    dispatched_at: null,
    consecutive_errors: 0,
    created_at: '2026-09-29T00:00:00Z',
    updated_at: '2026-09-29T00:00:00Z',
}

describe('ReportExpectedImpact', () => {
    let logic: ReturnType<typeof inboxReportDetailLogic.build>
    let approvalRequests: string[]
    let approvalFailures: Set<string>

    beforeEach(async () => {
        approvalRequests = []
        approvalFailures = new Set()
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:id/artefacts/': { results: [] },
                '/api/projects/:team_id/signals/reports/:id/signals/': { signals: [] },
                '/api/projects/:team_id/signals/reports/:id/checks/': { results: [] },
                '/api/projects/:team_id/signals/reports/available_reviewers/': [],
            },
            post: {
                '/api/projects/:team_id/signals/reports/:id/checks/:check_id/approve/': ({ request }) => {
                    const checkId = new URL(request.url).pathname.split('/').filter(Boolean).at(-2)!
                    approvalRequests.push(checkId)
                    if (approvalFailures.delete(checkId)) {
                        return [500, {}]
                    }
                    return [
                        200,
                        {
                            ...logic.values.reportChecks?.find((check) => check.id === checkId),
                            approved_at: '2026-09-30T00:00:00Z',
                        },
                    ]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SIGNALS_REPORT_CHECKS_REPLACE], {
            [FEATURE_FLAGS.SIGNALS_REPORT_CHECKS_REPLACE]: true,
        })
        inboxTaskKickoffLogic.mount()
        logic = inboxReportDetailLogic({ reportId: report.id, report })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
        jest.restoreAllMocks()
    })

    function renderMeasurements(checks: SignalReportCheckApi[]): void {
        logic.actions.loadReportChecksSuccess(checks)
        render(<ReportExpectedImpact report={report} reportUrl="https://example.com/report-1" />)
    }

    it('uses check goals and excludes investigations and replaced checks', async () => {
        renderMeasurements([
            check,
            { ...check, id: 'replaced', status: 'cancelled' },
            { ...check, id: 'investigation', kind: 'agent', config: { instructions: 'Re-read the issue.' } },
        ])

        expect(screen.getByText('Checkout errors stay below 5: at most 5 users')).toBeInTheDocument()
        expect(screen.queryByText(/Failed checkouts/)).not.toBeInTheDocument()
        expect(screen.getByText('Baseline: 20 users')).toBeInTheDocument()
        expect(screen.getAllByText('Chart')).toHaveLength(1)
        expect(screen.queryByText(/999/)).not.toBeInTheDocument()

        await userEvent.setup().click(screen.getByText('Suggest different metrics'))
        expect(screen.getByText('Describe what success would look like')).toBeInTheDocument()
        expect(screen.getByText('Ask AI to update checks').closest('button')).toHaveAttribute('aria-disabled', 'true')
    })

    it('disables metric suggestions until the replacement tool is available', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SIGNALS_REPORT_CHECKS_REPLACE]: false })
        renderMeasurements([check])
        expect(screen.getByText('Suggest different metrics').closest('button')).toHaveAttribute('aria-disabled', 'true')
    })

    it('caps visible measurements after skipping malformed check configs', () => {
        renderMeasurements([
            { ...check, id: 'malformed', config: { instructions: 'Legacy malformed metric check' } },
            ...Array.from({ length: 7 }, (_, index) => ({ ...check, id: `valid-${index}` })),
        ])

        expect(screen.getAllByText('Chart')).toHaveLength(6)
    })

    it('approves open measurements and retries only the failed approval', async () => {
        approvalFailures.add('check-2')
        renderMeasurements([check, { ...check, id: 'check-2' }, { ...check, id: 'finished', status: 'passed' }])
        const user = userEvent.setup()

        await user.click(screen.getByText('Looks good'))
        await waitFor(() => expect(logic.values.approvingCheckIds).toEqual([]))
        expect(screen.getAllByText(/Approved measurement/)).toHaveLength(1)
        expect(approvalRequests).toEqual(['check-1', 'check-2'])
        await user.click(screen.getByText('Looks good'))
        await waitFor(() => expect(screen.getAllByText(/Approved measurement/)).toHaveLength(2))
        expect(approvalRequests).toEqual(['check-1', 'check-2', 'check-2'])
        expect(logic.values.reportChecks?.every((check) => check.next_run_at === '2026-10-13T00:00:00Z')).toBe(true)
    })

    it('shows range goals and verdicts, and does not offer approval or replacement for finished checks', () => {
        renderMeasurements([
            {
                ...check,
                status: 'passed',
                config: { ...check.config, comparison: { operator: 'between', bounds: { lower: 2, upper: 8 } } },
            },
            { ...check, id: 'failed', status: 'failed', approved_at: '2026-09-30T00:00:00Z' },
        ])

        expect(screen.getByText('Checkout errors stay below 5: between 2 users and 8 users')).toBeInTheDocument()
        expect(screen.getByText(/Still holds/)).toBeInTheDocument()
        expect(screen.getByText(/No longer holds/)).toBeInTheDocument()
        expect(screen.queryByText(/(Proposed|Approved) measurement/)).not.toBeInTheDocument()
        expect(screen.getByText('Looks good').closest('button')).toHaveAttribute('aria-disabled', 'true')
        expect(screen.getByText('Suggest different metrics').closest('button')).toHaveAttribute('aria-disabled', 'true')
    })

    it('shows a failed check load and loads again on retry', async () => {
        useMocks({ get: { '/api/projects/:team_id/signals/reports/:id/checks/': () => [500, {}] } })
        logic.unmount()
        logic = inboxReportDetailLogic({ reportId: report.id, report })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        render(<ReportExpectedImpact report={report} reportUrl="https://example.com/report-1" />)

        expect(screen.getByText("Couldn't load the measurements.")).toBeInTheDocument()
        expect(screen.queryByText('Loading measurements…')).not.toBeInTheDocument()

        useMocks({ get: { '/api/projects/:team_id/signals/reports/:id/checks/': { results: [check] } } })
        await userEvent.setup().click(screen.getByText('Try again'))

        expect(await screen.findByText('Checkout errors stay below 5: at most 5 users')).toBeInTheDocument()
        expect(screen.queryByText("Couldn't load the measurements.")).not.toBeInTheDocument()
    })

    it('does not fall back to report queries when a check query is redacted', () => {
        renderMeasurements([{ ...check, config: { ...check.config, query: null, baseline_value: null } }])

        expect(screen.getByText('The query is not available to you.')).toBeInTheDocument()
        expect(screen.queryByText('Chart')).not.toBeInTheDocument()
        expect(screen.queryByText('View measurement query')).not.toBeInTheDocument()
        expect(screen.queryByText(/Baseline:/)).not.toBeInTheDocument()
        expect(screen.getByText('Looks good').closest('button')).toHaveAttribute('aria-disabled', 'true')
    })

    it('shows failed verdicts and offers a retry after checks fail to load', async () => {
        renderMeasurements([{ ...check, status: 'failed', last_run_at: '2026-09-30T00:00:00Z' }])
        expect(screen.getByText('No longer holds')).toBeInTheDocument()
        expect(screen.queryByText(/Proposed measurement/)).not.toBeInTheDocument()
        cleanup()
        logic.actions.loadReportChecksSuccess([])
        logic.actions.loadReportChecksFailure('Request failed')
        render(<ReportExpectedImpact report={report} reportUrl="https://example.com/report-1" />)
        expect(screen.getByText("Couldn't load the measurements.")).toBeInTheDocument()
        expect(screen.queryByText('Looks good')).not.toBeInTheDocument()
        await userEvent.setup().click(screen.getByText('Try again'))
        await waitFor(() => expect(logic.values.reportChecksError).toBeNull())
        await expectLogic(logic).toFinishAllListeners()
    })
})
