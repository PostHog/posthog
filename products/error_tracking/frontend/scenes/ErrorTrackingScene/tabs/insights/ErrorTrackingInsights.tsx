import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'

import { ChartCard } from './ChartCard'
import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { InsightsFilters } from './InsightsFilters'
import { SummaryStats } from './SummaryStats'

export function ErrorTrackingInsights(): JSX.Element {
    const { exceptionVolumeQuery, affectedUsersQuery, crashFreeSessionsQuery, summaryStatsLoading } =
        useValues(errorTrackingInsightsLogic)
    const { loadSummaryStats } = useActions(errorTrackingInsightsLogic)

    return (
        <div className="space-y-4">
            <SceneStickyBar showBorderBottom={false}>
                <InsightsFilters
                    reload={
                        <LemonButton
                            type="tertiary"
                            size="small"
                            onClick={() => loadSummaryStats(null)}
                            icon={summaryStatsLoading ? <Spinner textColored /> : <IconRefresh />}
                            tooltip={summaryStatsLoading ? 'Loading...' : 'Reload'}
                        />
                    }
                />
            </SceneStickyBar>
            <SummaryStats />

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                <ChartCard
                    title="Exception volume"
                    description="Exceptions per day"
                    query={exceptionVolumeQuery}
                    chartKey="exception_volume"
                />
                <ChartCard
                    title="Affected users"
                    description="Unique users experiencing exceptions"
                    query={affectedUsersQuery}
                    chartKey="affected_users"
                />
                <ChartCard
                    title="Crash-free sessions"
                    description="Percentage of sessions without any exceptions"
                    query={crashFreeSessionsQuery}
                    chartKey="crash_free_sessions"
                />
            </div>
        </div>
    )
}
