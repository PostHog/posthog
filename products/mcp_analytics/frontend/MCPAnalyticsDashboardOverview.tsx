import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { type ChartTheme } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { McpDateFilter } from './components/McpDateFilter'
import { ActivityChart } from './dashboard/ActivityChart'
import { HarnessDonut } from './dashboard/HarnessDonut'
import { KpiTiles } from './dashboard/KpiTiles'
import { NotableSessionsTable } from './dashboard/NotableSessionsTable'
import { ToolErrorRateChart } from './dashboard/ToolErrorRateChart'
import { ToolUsageChart } from './dashboard/ToolUsageChart'
import { MCPAnalyticsFirstLook } from './firstLook/MCPAnalyticsFirstLook'
import { mcpDashboardOverviewLogic } from './mcpDashboardOverviewLogic'

export function MCPAnalyticsDashboardOverview(): JSX.Element {
    const {
        kpis,
        kpisLoading,
        intentClusterCount,
        notableSessions,
        sessionRowsLoading,
        harnessRows,
        harnessRowsLoading,
        dailyActivity,
        activityRowsLoading,
        toolDailySeries,
        toolDailyRowsLoading,
        toolRows,
        toolRowsLoading,
        dateFilter,
        interval,
        filterTestAccounts,
        propertyFilters,
    } = useValues(mcpDashboardOverviewLogic)
    const { setDateFilter, setFilterTestAccounts, setPropertyFilters } = useActions(mcpDashboardOverviewLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const { timezone } = useValues(teamLogic)

    // buildTheme() reads CSS vars from the DOM; isDarkModeOn is the dep that forces a recompute when
    // the theme flips (it isn't passed as an argument).
    const theme = useMemo<ChartTheme>(() => buildTheme(), [isDarkModeOn])

    return (
        <div className="flex flex-col gap-4">
            <MCPAnalyticsFirstLook />
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-3">
                    <McpDateFilter
                        dateFrom={dateFilter.dateFrom}
                        dateTo={dateFilter.dateTo}
                        onChange={(dateFrom, dateTo) => setDateFilter(dateFrom, dateTo)}
                        dataAttr="mcp-dashboard-date-filter"
                    />
                    <div data-attr="mcp-dashboard-property-filter">
                        <PropertyFilters
                            pageKey="mcp-dashboard-overview"
                            propertyFilters={propertyFilters}
                            onChange={setPropertyFilters}
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.EventProperties,
                                TaxonomicFilterGroupType.EventFeatureFlags,
                            ]}
                            eventNames={['$mcp_tool_call']}
                            buttonText="Add filter"
                        />
                    </div>
                </div>
                <TestAccountFilterSwitch
                    checked={filterTestAccounts}
                    onChange={setFilterTestAccounts}
                    data-attr="mcp-dashboard-test-account-filter"
                />
            </div>
            <section data-quill>
                <h2 className="mb-4 text-xl font-semibold text-primary">Key metrics</h2>
                <KpiTiles kpis={kpis} intentClusterCount={intentClusterCount} kpisLoading={kpisLoading} theme={theme} />
            </section>
            <section data-quill>
                <h2 className="mb-4 text-xl font-semibold text-primary">Usage</h2>
                <div className="flex flex-col gap-[22px]">
                    <div className="grid grid-cols-1 gap-[22px] lg:grid-cols-3">
                        <div className="flex lg:col-span-2">
                            <ActivityChart
                                daily={dailyActivity}
                                loading={activityRowsLoading}
                                theme={theme}
                                timezone={timezone}
                                interval={interval}
                            />
                        </div>
                        <HarnessDonut rows={harnessRows} loading={harnessRowsLoading} theme={theme} />
                    </div>
                    <div className="grid grid-cols-1 gap-[22px] lg:grid-cols-2">
                        <ToolErrorRateChart rows={toolRows} loading={toolRowsLoading} theme={theme} />
                        <NotableSessionsTable sessions={notableSessions} loading={sessionRowsLoading} />
                    </div>
                    <ToolUsageChart
                        data={toolDailySeries}
                        loading={toolDailyRowsLoading}
                        theme={theme}
                        timezone={timezone}
                        interval={interval}
                    />
                </div>
            </section>
        </div>
    )
}
