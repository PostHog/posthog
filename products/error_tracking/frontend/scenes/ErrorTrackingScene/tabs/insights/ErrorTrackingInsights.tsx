import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { QuickFilterContext } from '~/queries/schema/schema-general'
import { PropertyFilterType } from '~/types'

import { NON_ISSUE_TAXONOMIC_GROUP_TYPES } from 'products/error_tracking/frontend/components/IssueFilters/consts'
import { FilterBar } from 'products/error_tracking/frontend/components/IssueFilters/FilterBar'
import {
    SearchBarVariantToggle,
    useErrorTrackingSearchBarRedesign,
} from 'products/error_tracking/frontend/components/IssueFilters/SearchBarVariantToggle'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../errorTrackingSceneLogic'
import { ChartCard } from './ChartCard'
import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { InsightsFilters } from './InsightsFilters'
import { SummaryStats } from './SummaryStats'

export function ErrorTrackingInsights(): JSX.Element {
    const { exceptionVolumeQuery, affectedUsersQuery, crashFreeSessionsQuery, summaryStatsLoading } =
        useValues(errorTrackingInsightsLogic)
    const { loadSummaryStats } = useActions(errorTrackingInsightsLogic)
    const newSearchBar = useErrorTrackingSearchBarRedesign()

    return (
        <>
            {newSearchBar && (
                <SceneStickyBar showBorderBottom={false} className="py-2 -mt-2 mb-2">
                    <div className="relative">
                        <SearchBarVariantToggle />
                        <FilterBar
                            reload={
                                <LemonButton
                                    type="tertiary"
                                    size="small"
                                    onClick={() => loadSummaryStats(null)}
                                    icon={summaryStatsLoading ? <Spinner textColored /> : <IconRefresh />}
                                    tooltip={summaryStatsLoading ? 'Loading...' : 'Reload'}
                                />
                            }
                            logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                            quickFilterContext={QuickFilterContext.ErrorTrackingIssueFilters}
                            taxonomicGroupTypes={NON_ISSUE_TAXONOMIC_GROUP_TYPES}
                            excludeFilterTypes={[PropertyFilterType.ErrorTrackingIssue]}
                            showIssueControls={false}
                            showSearch={false}
                        />
                    </div>
                </SceneStickyBar>
            )}
            <div className="space-y-4">
                {!newSearchBar && (
                    <div className="relative border rounded bg-surface-primary p-2 space-y-2">
                        <SearchBarVariantToggle />
                        <InsightsFilters />
                    </div>
                )}
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
        </>
    )
}
