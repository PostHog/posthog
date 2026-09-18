import { render, screen } from '@testing-library/react'
import { combineUrl, router } from 'kea-router'

import { buildTheme } from 'lib/charts/utils/theme'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { type KPIMetric } from '../mcpDashboardOverviewLogic'
import { KpiTiles } from './KpiTiles'

const METRIC: KPIMetric = {
    value: 1,
    previousValue: 1,
    deltaPct: null,
    sparkline: [],
    sparklineLabels: [],
    goodDirection: 'up',
}

const EVENT_FILTER: AnyPropertyFilter = {
    key: '$mcp_tool_name',
    value: ['create_insight'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

describe('KpiTiles', () => {
    beforeEach(() => initKeaTests())

    it('keeps dashboard filters in Sessions and Tool quality links', () => {
        const searchParams = {
            date_from: '-7d',
            properties: [EVENT_FILTER],
            filter_test_accounts: false,
        }
        router.actions.push(urls.mcpAnalyticsDashboard(), searchParams)

        render(
            <KpiTiles
                kpis={{ sessions: METRIC, toolCalls: METRIC, errorRatePct: METRIC, p95LatencyMs: METRIC }}
                users={METRIC}
                intentClusterCount={METRIC}
                kpisLoading={false}
                usersLoading={false}
                showIntentClusters={false}
                theme={buildTheme()}
                interval="day"
                incompleteTail={false}
            />
        )

        expect(screen.getByText('Sessions').closest('a')?.getAttribute('href')).toContain(
            combineUrl(urls.mcpAnalyticsSessions(), searchParams).url
        )
        expect(screen.getByText('Tool calls').closest('a')?.getAttribute('href')).toContain(
            combineUrl(urls.mcpAnalyticsToolQuality(), searchParams).url
        )
    })
})
