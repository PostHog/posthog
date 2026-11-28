import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SignalReportCheckApi, SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

import { MONITORING_MOCK_NOW, monitoringChecksForReport, monitoringRows } from '../../__mocks__/monitoringMocks'
import { MonitoringEvidence } from './MonitoringEvidence'

function MockReportCheckMetricChart({
    timeline,
    monitoring,
    queryTeamId,
}: {
    timeline: { endsAt: string }
    monitoring?: { endsAt: string | null }
    queryTeamId?: number
}): JSX.Element {
    return (
        <div>
            Sidebar metric chart
            <span data-attr="timeline-ends-at">{timeline.endsAt}</span>
            <span data-attr="monitoring-ends-at">{monitoring?.endsAt}</span>
            <span data-attr="query-team-id">{queryTeamId}</span>
        </div>
    )
}

jest.mock('../detail/ReportCheckMetricChart', () => ({
    ReportCheckMetricChart: MockReportCheckMetricChart,
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

    it('shows a failed check load and loads the chart on retry', async () => {
        const report = monitoringRows[3]! as unknown as SignalReportListApi
        const summary = report.monitoring_summary!
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': { results: [] },
                '/api/projects/:team_id/signals/reports/:report_id/checks/': () => [500, {}],
            },
        })
        initKeaTests()

        render(<MonitoringEvidence report={report} summary={summary} now={Date.parse(MONITORING_MOCK_NOW)} />)

        expect(await screen.findByText("Couldn't load the monitoring chart.")).toBeInTheDocument()
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:report_id/checks/': {
                    results: monitoringChecksForReport(report),
                },
            },
        })
        await userEvent.setup().click(screen.getAllByText('Retry')[0])

        expect(await screen.findByText('Sidebar metric chart')).toBeInTheDocument()
        expect(screen.queryByText("Couldn't load the monitoring chart.")).not.toBeInTheDocument()
    })

    it('loads checks and chart data from the parent project when a child environment is selected', async () => {
        const report = monitoringRows[3]! as unknown as SignalReportListApi
        const requestedPaths: string[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': { results: [] },
                '/api/projects/:team_id/signals/reports/:report_id/checks/': ({ request }) => {
                    requestedPaths.push(new URL(request.url).pathname)
                    return [200, { results: monitoringChecksForReport(report) }]
                },
            },
        })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, id: 4242, project_id: 99 }, { ...MOCK_DEFAULT_PROJECT, id: 99 })

        render(
            <MonitoringEvidence
                report={report}
                summary={report.monitoring_summary!}
                now={Date.parse(MONITORING_MOCK_NOW)}
            />
        )

        expect(await screen.findByText('Sidebar metric chart')).toBeInTheDocument()
        expect(requestedPaths).toEqual([`/api/projects/99/signals/reports/${report.id}/checks/`])
        expect(screen.getByTestId('query-team-id')).toHaveTextContent('99')
    })

    it('loads evidence when the lead check has a stored query but no report metric ID', async () => {
        const sourceReport = monitoringRows[3]! as unknown as SignalReportListApi
        const sourceCheck = monitoringChecksForReport(sourceReport)[0]!
        const summary = {
            ...sourceReport.monitoring_summary!,
            lead_check: { ...sourceReport.monitoring_summary!.lead_check!, metric_id: null },
        }
        const report = { ...sourceReport, monitoring_summary: summary }
        const check = {
            ...sourceCheck,
            config: { ...sourceCheck.config, metric_id: null },
        } as SignalReportCheckApi
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': { results: [] },
                '/api/projects/:team_id/signals/reports/:report_id/checks/': { results: [check] },
            },
        })
        initKeaTests()

        render(<MonitoringEvidence report={report} summary={summary} now={Date.parse(MONITORING_MOCK_NOW)} />)

        expect(await screen.findByText('Sidebar metric chart')).toBeInTheDocument()
    })

    it("limits the chart to the lead check's monitoring window", async () => {
        const sourceReport = monitoringRows[3]! as unknown as SignalReportListApi
        const leadEndsAt = '2026-11-19T17:00:00.000Z'
        const summary = {
            ...sourceReport.monitoring_summary!,
            ends_at: '2026-11-25T17:00:00.000Z',
            lead_check: { ...sourceReport.monitoring_summary!.lead_check!, ends_at: leadEndsAt },
        }
        const report = { ...sourceReport, monitoring_summary: summary }
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
        expect(screen.getByTestId('timeline-ends-at')).toHaveTextContent(leadEndsAt)
        expect(screen.getByTestId('monitoring-ends-at')).toHaveTextContent(leadEndsAt)
    })
})
