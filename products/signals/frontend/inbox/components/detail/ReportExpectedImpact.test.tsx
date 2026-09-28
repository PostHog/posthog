import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { reportMetricsFixture } from '../../__mocks__/reportMetricMocks'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport, SignalReportArtefact, SignalReportStatus } from '../../types'
import { ReportExpectedImpact } from './ReportExpectedImpact'

jest.mock('./ReportExpectedImpactChart', () => ({ ReportExpectedImpactChart: () => <div>Chart</div> }))

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
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('saves all current proposals through Keep an eye without a separate approval button', async () => {
        const activateMeasurement = jest.spyOn(api.signalReports, 'activateMeasurement').mockResolvedValue(undefined)
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

        expect(screen.queryByRole('button', { name: 'Approve measurement' })).not.toBeInTheDocument()
        await user.click(screen.getByRole('button', { name: 'Keep an eye on this for me' }))

        await waitFor(() => expect(onApprovalComplete).toHaveBeenCalledTimes(1))
        expect(activateMeasurement).toHaveBeenCalledTimes(2)
        expect(activateMeasurement).toHaveBeenCalledWith(report.id, 'first')
        expect(activateMeasurement).toHaveBeenCalledWith(report.id, 'second')
        expect(screen.getAllByText(/Saved measurement/)).toHaveLength(2)

        await user.click(screen.getByRole('button', { name: 'Keep an eye on this for me' }))
        expect(activateMeasurement).toHaveBeenCalledTimes(2)
    })

    it('keeps failed proposals available to retry without re-saving successful ones', async () => {
        const activateMeasurement = jest
            .spyOn(api.signalReports, 'activateMeasurement')
            .mockImplementationOnce(async () => undefined)
            .mockRejectedValueOnce(new Error('Try again'))
            .mockResolvedValue(undefined)
        const user = userEvent.setup()
        render(
            <ReportExpectedImpact
                report={report}
                reportUrl="https://example.test/report-1"
                artefacts={[plan('first', 'one'), plan('second', 'two')]}
            />
        )

        await user.click(screen.getByRole('button', { name: 'Keep an eye on this for me' }))
        await waitFor(() => expect(screen.getAllByText(/Saved measurement/)).toHaveLength(1))
        await user.click(screen.getByRole('button', { name: 'Keep an eye on this for me' }))

        await waitFor(() => expect(screen.getAllByText(/Saved measurement/)).toHaveLength(2))
        expect(activateMeasurement.mock.calls.map(([, id]) => id)).toEqual(['first', 'second', 'second'])
    })

    it('does not offer follow-ups without a proposal', () => {
        render(<ReportExpectedImpact report={report} reportUrl="https://example.test/report-1" artefacts={[]} />)

        expect(screen.getByRole('button', { name: 'Keep an eye on this for me' })).toHaveAttribute(
            'aria-disabled',
            'true'
        )
        expect(screen.getByRole('button', { name: 'Suggest different metrics' })).toBeEnabled()
    })
})
