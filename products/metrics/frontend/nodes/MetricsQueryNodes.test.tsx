import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { Query } from '~/queries/Query/Query'
import { MetricsHistogramQuery, MetricsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightShortId } from '~/types'

const METRICS_QUERY: MetricsQuery = {
    kind: NodeKind.MetricsQuery,
    clauses: [{ name: 'a', metricName: 'request_duration', aggregation: 'sum' }],
    dateRange: { date_from: '-1h' },
}

const HISTOGRAM_QUERY: MetricsHistogramQuery = {
    kind: NodeKind.MetricsHistogramQuery,
    metricName: 'request_duration',
    dateRange: { date_from: '-1h' },
}

describe('metrics query nodes', () => {
    beforeEach(() => {
        useMocks({ post: { '/api/environments/:team_id/query/:kind': () => [200, { results: [] }] } })
        initKeaTests()
    })

    afterEach(() => cleanup())

    it.each([
        ['time series in a dashboard tile', METRICS_QUERY, true, false],
        ['time series in the insight scene opened from a dashboard', METRICS_QUERY, false, true],
        ['heatmap in a dashboard tile', HISTOGRAM_QUERY, true, false],
        ['heatmap in the insight scene opened from a dashboard', HISTOGRAM_QUERY, false, true],
    ])('%s', (_name, query, embedded, expectMinHeight) => {
        const { container } = render(
            <Query
                query={query}
                readOnly
                embedded={embedded}
                context={{ insightProps: { dashboardItemId: 'abc123' as InsightShortId, dashboardId: 1 } }}
            />
        )
        expect(container.querySelector('.min-h-\\[200px\\]') !== null).toBe(expectMinHeight)
    })
})
