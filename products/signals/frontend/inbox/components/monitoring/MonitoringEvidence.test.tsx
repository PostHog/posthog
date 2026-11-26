import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

import { MONITORING_MOCK_NOW, monitoringChecksForReport, monitoringRows } from '../../__mocks__/monitoringMocks'
import { MonitoringEvidence } from './MonitoringEvidence'

jest.mock('../detail/ReportCheckMetricChart', () => ({
    ReportCheckMetricChart: () => <div>Sidebar metric chart</div>,
}))

describe('MonitoringEvidence', () => {
    afterEach(cleanup)

    it('loads the full check and renders the report sidebar chart when the list snapshot has no series', async () => {
        const sourceReport = monitoringRows[3]!
        const report = {
            ...sourceReport,
            metrics: sourceReport.metrics!.map((metric) => ({ ...metric, series: null, series_buckets: null })),
        } as unknown as SignalReportListApi
        const summary = report.monitoring_summary!
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': { results: [] },
                '/api/projects/:team_id/signals/reports/:report_id/checks/': {
                    results: monitoringChecksForReport(report),
                },
            },
        })
        initKeaTests()

        render(<MonitoringEvidence report={report} summary={summary} now={Date.parse(MONITORING_MOCK_NOW)} />)

        expect(await screen.findByText('Sidebar metric chart')).toBeInTheDocument()
    })
})
