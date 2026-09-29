import { MOCK_TEAM_ID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { signalsReportsArtefactsActivateCreate } from 'products/signals/frontend/generated/api'
import type { SignalReportArtefactWriteResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { reportMetricsFixture } from '../../__mocks__/reportMetricMocks'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport, SignalReportArtefact, SignalReportStatus } from '../../types'
import { ReportExpectedImpact } from './ReportExpectedImpact'

jest.mock('./ReportExpectedImpactChart', () => ({ ReportExpectedImpactChart: () => <div>Chart</div> }))
jest.mock('products/signals/frontend/generated/api', () => ({ signalsReportsArtefactsActivateCreate: jest.fn() }))

const mockActivateMeasurement = jest.mocked(signalsReportsArtefactsActivateCreate)

const report: SignalReport = {
    id: 'report-1',
    title: 'Incomplete setup',
    summary: 'Setup fails.',
    status: SignalReportStatus.READY,
    total_weight: 0,
    signal_count: 1,
    artefact_count: 0,
    is_suggested_reviewer: false,
    created_at: '2026-08-29T00:00:00Z',
    updated_at: '2026-08-29T00:00:00Z',
}

const activatedPlanResponse: SignalReportArtefactWriteResponseApi = {
    id: 'saved-plan',
    claim_id: null,
    report_id: report.id,
    type: 'impact_measurement_plan',
    content: {},
    created_at: '2026-08-29T00:00:00Z',
    updated_at: '2026-08-29T00:00:00Z',
    task_id: null,
}

function plan(id: string, metricId: string): SignalReportArtefact {
    return {
        id,
        type: 'impact_measurement_plan',
        created_at: '2026-08-29T00:00:00Z',
        content: {
            metric_id: metricId,
            title: `Outcome ${metricId}`,
            kind: reportMetricsFixture[0].kind,
            query: reportMetricsFixture[0].query,
            goal_value: 50,
            goal_direction: 'at_most',
            goal_grain: 'per_interval',
            decision_window_days: 7,
            activated: false,
        },
    }
}

describe('ReportExpectedImpact', () => {
    beforeEach(() => {
        initKeaTests()
        inboxTaskKickoffLogic.mount()
        mockActivateMeasurement.mockReset()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('saves all current proposals through Keep an eye without a separate approval button', async () => {
        mockActivateMeasurement.mockResolvedValue(activatedPlanResponse)
        const onApprovalComplete = jest.fn()
        const user = userEvent.setup()
        render(
            <ReportExpectedImpact
                report={report}
                reportUrl="https://example.test/report-1"
                artefacts={[plan('first', 'one'), plan('second', 'two')]}
                onApprovalComplete={onApprovalComplete}
            />
        )

        expect(screen.queryByText('Approve measurement')).not.toBeInTheDocument()
        await user.click(screen.getByText('Keep an eye on this for me'))

        await waitFor(() => expect(onApprovalComplete).toHaveBeenCalledTimes(1))
        expect(mockActivateMeasurement).toHaveBeenCalledTimes(2)
        expect(mockActivateMeasurement).toHaveBeenCalledWith(String(MOCK_TEAM_ID), report.id, 'first')
        expect(mockActivateMeasurement).toHaveBeenCalledWith(String(MOCK_TEAM_ID), report.id, 'second')
        expect(screen.getAllByText(/Saved measurement/)).toHaveLength(2)

        await user.click(screen.getByText('Keep an eye on this for me'))
        expect(mockActivateMeasurement).toHaveBeenCalledTimes(2)
    })

    it('keeps failed proposals available to retry without re-saving successful ones', async () => {
        mockActivateMeasurement
            .mockResolvedValueOnce(activatedPlanResponse)
            .mockRejectedValueOnce(new Error('Try again'))
            .mockResolvedValue(activatedPlanResponse)
        const user = userEvent.setup()
        render(
            <ReportExpectedImpact
                report={report}
                reportUrl="https://example.test/report-1"
                artefacts={[plan('first', 'one'), plan('second', 'two')]}
            />
        )

        await user.click(screen.getByText('Keep an eye on this for me'))
        await waitFor(() => expect(screen.getAllByText(/Saved measurement/)).toHaveLength(1))
        await user.click(screen.getByText('Keep an eye on this for me'))

        await waitFor(() => expect(screen.getAllByText(/Saved measurement/)).toHaveLength(2))
        expect(mockActivateMeasurement.mock.calls.map(([, , id]) => id)).toEqual(['first', 'second', 'second'])
    })

    it('does not offer follow-ups without a proposal', () => {
        render(<ReportExpectedImpact report={report} reportUrl="https://example.test/report-1" artefacts={[]} />)

        expect(screen.getByText('Keep an eye on this for me').closest('button')).toHaveAttribute(
            'aria-disabled',
            'true'
        )
        expect(screen.getByText('Suggest different metrics').closest('button')).toBeEnabled()
    })

    it('bounds the number of charts and approval requests for older oversized reports', async () => {
        mockActivateMeasurement.mockResolvedValue(activatedPlanResponse)
        const user = userEvent.setup()
        const artefacts = Array.from({ length: 7 }, (_, index) => plan(`plan-${index}`, `outcome-${index}`))
        render(<ReportExpectedImpact report={report} reportUrl="https://example.test/report-1" artefacts={artefacts} />)

        expect(screen.getAllByText('Chart')).toHaveLength(6)
        expect(screen.queryByText(/Outcome outcome-6/)).not.toBeInTheDocument()

        await user.click(screen.getByText('Keep an eye on this for me'))
        await waitFor(() => expect(mockActivateMeasurement).toHaveBeenCalledTimes(6))
    })
})
