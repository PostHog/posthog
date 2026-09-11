import { render } from '@testing-library/react'
import { router } from 'kea-router'

import { buildTheme } from 'lib/charts/utils/theme'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { KPIMetric } from '../mcpDashboardOverviewLogic'
import { KpiTiles } from './KpiTiles'

describe('KpiTiles', () => {
    it.each([true, false])('keeps shared filters in every drill-down with test-account filtering %s', (excluded) => {
        initKeaTests()
        const searchParams = {
            properties: [{ key: '$mcp_client_name', value: ['claude-code'], operator: 'exact', type: 'event' }],
            filter_test_accounts: excluded,
            date_from: '-14d',
        }
        router.actions.push(urls.mcpAnalyticsDashboard(), searchParams)
        const metric: KPIMetric = {
            value: 1,
            previousValue: 1,
            deltaPct: 0,
            sparkline: [],
            sparklineLabels: [],
            goodDirection: 'up',
        }
        const { container } = render(
            <KpiTiles
                kpis={{ sessions: metric, toolCalls: metric, errorRatePct: metric, p95LatencyMs: metric }}
                users={metric}
                intentClusterCount={metric}
                kpisLoading={false}
                usersLoading={false}
                showIntentClusters
                theme={buildTheme()}
                interval="day"
                incompleteTail={false}
            />
        )

        const links = container.querySelectorAll('a')
        expect(links).toHaveLength(6)
        for (const link of links) {
            const params = new URL(link.href).searchParams
            expect(JSON.parse(params.get('properties')!)).toEqual(searchParams.properties)
            expect(params.get('filter_test_accounts')).toBe(String(excluded))
            expect(params.get('date_from')).toBe('-14d')
        }
    })
})
