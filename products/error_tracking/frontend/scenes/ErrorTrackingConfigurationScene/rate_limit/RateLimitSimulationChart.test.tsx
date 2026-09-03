import { cleanup, render } from '@testing-library/react'

import { TimeSeriesBarChart } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'

import { RateLimitSimulationChart } from './RateLimitSimulationChart'

jest.mock('@posthog/quill-charts', () => ({
    ...jest.requireActual('@posthog/quill-charts'),
    TimeSeriesBarChart: jest.fn(() => <div data-testid="rate-limit-chart" />),
}))

jest.mock('lib/charts/hooks', () => ({
    useChartTheme: () => ({ colors: ['#000'] }),
    useChartConfig: (buildConfig: () => unknown) => buildConfig(),
}))

const mockTimeSeriesBarChart = jest.mocked(TimeSeriesBarChart)

describe('RateLimitSimulationChart', () => {
    beforeEach(() => {
        jest.useFakeTimers().setSystemTime(new Date('2024-11-03T08:00:00.000Z'))
        mockTimeSeriesBarChart.mockClear()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('keeps ISO labels distinct across a repeated local hour', () => {
        render(<RateLimitSimulationChart volume={[]} rateLimit={null} bucketMinutes={60} />)

        const labels = mockTimeSeriesBarChart.mock.calls[0][0].labels
        const repeatedHourLabels = labels.filter(
            (label) => dayjs(label).tz('America/New_York').format('MMM D, HH:mm') === 'Nov 3, 01:00'
        )

        expect(repeatedHourLabels).toEqual(['2024-11-03T05:00:00.000Z', '2024-11-03T06:00:00.000Z'])
        expect(new Set(labels).size).toBe(labels.length)
    })
})
