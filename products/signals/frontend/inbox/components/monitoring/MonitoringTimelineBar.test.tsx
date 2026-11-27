import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import type { SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

import { MONITORING_MOCK_NOW, monitoringRows } from '../../__mocks__/monitoringMocks'
import { MonitoringTimelineBar } from './MonitoringTimelineBar'

describe('MonitoringTimelineBar', () => {
    it('colors passing and failing readings green and yellow while leaving an unknown reading neutral', () => {
        const now = Date.parse(MONITORING_MOCK_NOW)
        const sourceReport = monitoringRows[3]!
        const report = {
            ...sourceReport,
            monitoring_summary: {
                ...sourceReport.monitoring_summary!,
                lead_check: {
                    ...sourceReport.monitoring_summary!.lead_check!,
                    readings: [
                        {
                            measured_at: new Date(now - 3_600_000).toISOString(),
                            matches: true,
                            observed_value: 1,
                            threshold: 2,
                        },
                        {
                            measured_at: new Date(now).toISOString(),
                            matches: false,
                            observed_value: 3,
                            threshold: 2,
                        },
                        {
                            measured_at: new Date(now + 3_600_000).toISOString(),
                            matches: null,
                            observed_value: null,
                            threshold: null,
                        },
                    ],
                },
            },
        } as unknown as SignalReportListApi

        const { container } = render(
            <div className="relative h-5">
                <MonitoringTimelineBar
                    report={report}
                    now={now}
                    axisStart={now - 24 * 3_600_000}
                    axisEnd={now + 24 * 3_600_000}
                    statusLabel="On track"
                />
            </div>
        )
        const readings = container.querySelectorAll('span.size-2')

        expect(readings).toHaveLength(3)
        expect(readings[0]).toHaveClass('bg-success')
        expect(readings[1]).toHaveClass('bg-warning')
        expect(readings[2]).toHaveClass('bg-surface-primary')
    })
})
