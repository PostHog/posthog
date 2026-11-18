import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'

import { ChartCard } from './ChartCard'
import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { InsightsFilters } from './InsightsFilters'
import { MetricTiles } from './MetricTiles'
import { ReleaseBreakdownCards } from './ReleaseBreakdownCards'

function InsightsSection({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <section>
            <h2 className="mb-4 text-xl font-semibold text-primary">{title}</h2>
            {children}
        </section>
    )
}

export function ErrorTrackingInsights(): JSX.Element {
    const {
        exceptionVolumeQuery,
        issuesCreatedQuery,
        affectedUsersQuery,
        crashFreeSessionsQuery,
        metrics,
        metricsLoading,
        incompleteTail,
        loadFailed,
    } = useValues(errorTrackingInsightsLogic)
    const { loadInsights } = useActions(errorTrackingInsightsLogic)

    return (
        <div>
            <SceneStickyBar className="-mt-4" showBorderBottom={false}>
                <InsightsFilters />
            </SceneStickyBar>
            <div className="flex flex-col gap-4">
                {loadFailed && (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadInsights() }}>
                        Couldn't load these insights. The numbers below may be out of date.
                    </LemonBanner>
                )}
                <InsightsSection title="Key metrics">
                    <MetricTiles metrics={metrics} loading={metricsLoading} incompleteTail={incompleteTail} />
                </InsightsSection>

                <InsightsSection title="Trends">
                    {/* Two charts side by side need real width, and the nav sidebar plus an open side
                        panel take most of a laptop window. Break on the tab's own width, not the
                        viewport's, so the pair stacks whenever the space actually ran out. */}
                    <div className="@container">
                        <div className="grid grid-cols-1 gap-4 @4xl:grid-cols-2">
                            <ChartCard
                                title="Exception volume"
                                description="Exceptions over time"
                                query={exceptionVolumeQuery}
                                chartKey="exception_volume"
                            />
                            <ChartCard
                                title="Issues created"
                                description="Issues seen for the first time"
                                query={issuesCreatedQuery}
                                chartKey="issues_created"
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
                </InsightsSection>

                <InsightsSection title="Releases">
                    <ReleaseBreakdownCards />
                </InsightsSection>
            </div>
        </div>
    )
}
