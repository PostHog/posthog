import { useValues } from 'kea'
import { useMemo } from 'react'

import { type ChartTheme } from '@posthog/quill-charts'
import '@posthog/quill-primitives/styles.css'

import { buildTheme } from 'lib/charts/utils/theme'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { ActivityChart } from './dashboard/ActivityChart'
import { HarnessDonut } from './dashboard/HarnessDonut'
import { KpiTiles } from './dashboard/KpiTiles'
import { NotableSessionsTable } from './dashboard/NotableSessionsTable'
import { ToolErrorRateChart } from './dashboard/ToolErrorRateChart'
import { ToolUsageChart } from './dashboard/ToolUsageChart'
import { mcpDashboardOverviewLogic } from './mcpDashboardOverviewLogic'

export function MCPAnalyticsDashboardOverview(): JSX.Element {
    const {
        kpis,
        kpisLoading,
        intentClusterCount,
        notableSessions,
        sessionRowsLoading,
        harnessRows,
        harnessRawRowsLoading,
        dailyActivity,
        activityRowsLoading,
        toolDailySeries,
        toolDailyRowsLoading,
        toolRows,
        toolRowsLoading,
    } = useValues(mcpDashboardOverviewLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const { timezone } = useValues(teamLogic)

    const theme = useMemo<ChartTheme>(() => buildTheme(), [isDarkModeOn])

    return (
        <div className="flex flex-col gap-10">
            <section>
                <h2 className="mb-4 text-xl font-semibold text-primary">Previous week's key metrics</h2>
                <KpiTiles kpis={kpis} intentClusterCount={intentClusterCount} kpisLoading={kpisLoading} theme={theme} />
            </section>
            <section>
                <h2 className="mb-4 text-xl font-semibold text-primary">Last month's usage</h2>
                <div className="flex flex-col gap-[22px]">
                    <div className="grid grid-cols-1 gap-[22px] lg:grid-cols-3">
                        <div className="flex lg:col-span-2">
                            <ActivityChart
                                daily={dailyActivity}
                                loading={activityRowsLoading}
                                theme={theme}
                                timezone={timezone}
                            />
                        </div>
                        <HarnessDonut rows={harnessRows} loading={harnessRawRowsLoading} theme={theme} />
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
                    />
                </div>
            </section>
        </div>
    )
}
