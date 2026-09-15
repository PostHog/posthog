import { useActions, useValues } from 'kea'

import { useChartTheme } from 'lib/charts/hooks'
import { FilterBar } from 'lib/components/FilterBar'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { McpDateFilter } from './components/McpDateFilter'
import { ActivityChart } from './dashboard/ActivityChart'
import { HarnessBarChart } from './dashboard/HarnessBarChart'
import { KpiTiles } from './dashboard/KpiTiles'
import { ModelBarChart } from './dashboard/ModelBarChart'
import { NotableSessionsTable } from './dashboard/NotableSessionsTable'
import { ToolErrorRateChart } from './dashboard/ToolErrorRateChart'
import { ToolUsageChart } from './dashboard/ToolUsageChart'
import { MCPAnalyticsFirstLook } from './firstLook/MCPAnalyticsFirstLook'
import { mcpDashboardOverviewLogic } from './mcpDashboardOverviewLogic'

export function MCPAnalyticsDashboardOverview(): JSX.Element {
    const {
        kpis,
        kpisLoading,
        users,
        usersLoading,
        intentClusterCount,
        notableSessions,
        sessionRowsLoading,
        harnessRows,
        harnessRowsLoading,
        modelRows,
        hasModelData,
        dailyActivity,
        activityRowsLoading,
        activityIncompleteTail,
        kpiIncompleteTail,
        toolDailySeries,
        toolDailyRowsLoading,
        toolRows,
        toolRowsLoading,
        dateFilter,
        interval,
        filterTestAccounts,
        propertyFilters,
        queryFilters,
    } = useValues(mcpDashboardOverviewLogic)
    const { setDateFilter, setFilterTestAccounts, setPropertyFilters } = useActions(mcpDashboardOverviewLogic)
    const { timezone } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const theme = useChartTheme()

    return (
        <div className="flex flex-col gap-4">
            <FilterBar
                left={
                    <>
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
                                    TaxonomicFilterGroupType.MCPProperties,
                                    TaxonomicFilterGroupType.EventProperties,
                                    TaxonomicFilterGroupType.EventFeatureFlags,
                                ]}
                                eventNames={['$mcp_tool_call']}
                                buttonText="Add filter"
                            />
                        </div>
                    </>
                }
                right={
                    <TestAccountFilterSwitch
                        checked={filterTestAccounts}
                        onChange={setFilterTestAccounts}
                        data-attr="mcp-dashboard-test-account-filter"
                    />
                }
            />
            <MCPAnalyticsFirstLook />
            <section data-quill>
                <h2 className="mb-4 text-xl font-semibold text-primary">Key metrics</h2>
                <KpiTiles
                    kpis={kpis}
                    users={users}
                    intentClusterCount={intentClusterCount}
                    kpisLoading={kpisLoading}
                    usersLoading={usersLoading}
                    showIntentClusters={!!featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_INTENT_ROUTING]}
                    theme={theme}
                    interval={interval}
                    incompleteTail={kpiIncompleteTail}
                />
            </section>
            <section data-quill>
                <h2 className="mb-4 text-xl font-semibold text-primary">Usage</h2>
                <div className="flex flex-col gap-[22px]">
                    <div
                        className={cn(
                            'grid grid-cols-1 gap-[22px]',
                            hasModelData ? 'lg:grid-cols-4' : 'lg:grid-cols-3'
                        )}
                    >
                        <div className="flex lg:col-span-2">
                            <ActivityChart
                                daily={dailyActivity}
                                loading={activityRowsLoading}
                                theme={theme}
                                timezone={timezone}
                                interval={interval}
                                incompleteTail={activityIncompleteTail}
                            />
                        </div>
                        <HarnessBarChart rows={harnessRows} loading={harnessRowsLoading} theme={theme} />
                        {hasModelData ? <ModelBarChart rows={modelRows} theme={theme} filters={queryFilters} /> : null}
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
