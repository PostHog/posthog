import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonBanner, LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { Onboarding } from './Onboarding'
import { RevenueAnalyticsFilters } from './RevenueAnalyticsFilters'
import { REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID, revenueAnalyticsLogic } from './revenueAnalyticsLogic'
import { revenueAnalyticsSettingsLogic } from './settings/revenueAnalyticsSettingsLogic'
import { GrossRevenueTile, MRRTile, MetricsTile, OverviewTile, TopCustomersTile } from './tiles'

export const scene: SceneExport = {
    component: RevenueAnalyticsScene,
    logic: revenueAnalyticsLogic,
    settingSectionId: 'environment-revenue-analytics',
}

export const PRODUCT_KEY = ProductKey.REVENUE_ANALYTICS
export const PRODUCT_THING_NAME = 'revenue source'

export function RevenueAnalyticsScene(): JSX.Element {
    const { dataWarehouseSources } = useValues(revenueAnalyticsSettingsLogic)
    const { revenueEnabledDataWarehouseSources, pausedRevenueViews, resumingSchedules } =
        useValues(revenueAnalyticsLogic)
    const { resumeAllPausedSchedules } = useActions(revenueAnalyticsLogic)

    const sourceRunningForTheFirstTime = revenueEnabledDataWarehouseSources?.find(
        (source) => source.status === 'Running' && !source.last_run_at
    )

    // Wait before binding/mounting the logics until we've finished loading the data warehouse sources
    if (dataWarehouseSources === null) {
        return <SpinnerOverlay sceneLevel />
    }

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.RevenueAnalytics].name}
                    description={sceneConfigurations[Scene.RevenueAnalytics].description}
                    resourceType={{
                        type: sceneConfigurations[Scene.RevenueAnalytics].iconType || 'default',
                    }}
                />

                <LemonBanner
                    type="info"
                    action={{ children: 'Send feedback', id: 'revenue-analytics-feedback-button' }}
                >
                    Revenue Analytics is in beta &ndash; we'd love your feedback and feature suggestions!
                    <br />
                    This product is optimized for small to medium businesses with under 20,000 transactions/month and
                    subscription-based revenue models.
                </LemonBanner>

                {sourceRunningForTheFirstTime && (
                    <LemonBanner
                        type="success"
                        dismissKey={`revenue-analytics-sync-in-progress-banner-${sourceRunningForTheFirstTime.id}`}
                        action={{ children: 'Refresh', onClick: () => window.location.reload() }}
                    >
                        One of your revenue data warehouse sources is running for the first time. <br />
                        This means you might not see all of your revenue data yet. <br />
                        We display partial data - most recent months first - while the initial sync is running. <br />
                        Refresh the page to see the latest data.
                    </LemonBanner>
                )}

                {pausedRevenueViews.length > 0 && (
                    <LemonBanner type="warning">
                        <div className="flex items-center justify-between gap-2">
                            <div>
                                <p className="font-semibold mb-1">
                                    {pausedRevenueViews.length} materialized view
                                    {pausedRevenueViews.length > 1 ? 's have' : ' has'} failed and{' '}
                                    {pausedRevenueViews.length > 1 ? 'their schedules are' : 'its schedule is'} paused
                                </p>
                                <p className="text-sm">
                                    This may affect your revenue analytics data. Resume the schedule
                                    {pausedRevenueViews.length > 1 ? 's' : ''} to restore automatic updates.
                                </p>
                            </div>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={resumeAllPausedSchedules}
                                loading={resumingSchedules}
                            >
                                Resume {pausedRevenueViews.length > 1 ? 'all' : ''} schedule
                                {pausedRevenueViews.length > 1 ? 's' : ''}
                            </LemonButton>
                        </div>
                    </LemonBanner>
                )}

                <RevenueAnalyticsSceneContent />
            </SceneContent>
        </BindLogic>
    )
}

const RevenueAnalyticsSceneContent = (): JSX.Element => {
    const [isOnboarding, setIsOnboarding] = useState(false)
    const { hasRevenueTables, hasRevenueEvents } = useValues(revenueAnalyticsLogic)
    const { reportRevenueAnalyticsViewed } = useActions(eventUsageLogic)
    const { addProductIntent } = useActions(teamLogic)

    useOnMountEffect(() => {
        reportRevenueAnalyticsViewed()
        addProductIntent({
            product_type: ProductKey.REVENUE_ANALYTICS,
            intent_context: ProductIntentContext.REVENUE_ANALYTICS_VIEWED,
        })
    })

    // Turn onboarding on if we haven't connected any revenue sources or events yet
    // We'll keep that stored in the state to make sure we don't "leave" the onboarding state
    // after we've entered it once
    useEffect(() => {
        if (!isOnboarding && !hasRevenueTables && !hasRevenueEvents) {
            setIsOnboarding(true)
        }
    }, [hasRevenueTables, hasRevenueEvents, isOnboarding])

    // Still loading from the server, so we'll show a spinner
    if (hasRevenueTables === null) {
        return <SpinnerOverlay sceneLevel />
    }

    // Hasn't connected any revenue sources or events yet, so we'll show the onboarding
    // Also, once we've entered the onboarding state, we'll stay in it until we purposefully leave it
    // rather than leaving as soon as we've connected a revenue source or event
    if (isOnboarding || (!hasRevenueTables && !hasRevenueEvents)) {
        return <Onboarding completeOnboarding={() => setIsOnboarding(false)} />
    }

    return (
        <div className={cn('RevenueAnalyticsDashboard -mt-2')}>
            <RevenueAnalyticsFilters />
            <RevenueAnalyticsTables />
        </div>
    )
}

const RevenueAnalyticsTables = (): JSX.Element => {
    return (
        <div className="flex flex-col gap-4 mt-4">
            <OverviewTile />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <MRRTile />
                <GrossRevenueTile />
                <MetricsTile />
                <TopCustomersTile />
            </div>
        </div>
    )
}
