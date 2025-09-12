import { BindLogic, useValues } from 'kea'

import { LemonBanner, SpinnerOverlay } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ProductKey } from '~/types'

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

export const PRODUCT_NAME = 'Revenue Analytics'
export const PRODUCT_KEY = ProductKey.REVENUE_ANALYTICS
export const PRODUCT_DESCRIPTION =
    'Track and analyze your revenue metrics to understand your business performance and growth.'
export const PRODUCT_THING_NAME = 'revenue source'

export function RevenueAnalyticsScene(): JSX.Element {
    const { dataWarehouseSources } = useValues(revenueAnalyticsSettingsLogic)
    const { revenueEnabledDataWarehouseSources } = useValues(revenueAnalyticsLogic)
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

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
                    name={PRODUCT_NAME}
                    description={PRODUCT_DESCRIPTION}
                    resourceType={{
                        type: 'revenue_analytics',
                    }}
                />
                <SceneDivider />

                <LemonBanner
                    type="info"
                    action={{ children: 'Send feedback', id: 'revenue-analytics-feedback-button' }}
                    className={cn(!newSceneLayout && 'mb-2')}
                >
                    <p>
                        Revenue Analytics is in beta. Please let us know what you'd like to see here and/or report any
                        issues directly to us!
                    </p>
                    <p>
                        At this stage, Revenue Analytics is optimized for small/medium-sized companies. If you process
                        more than 20,000 transactions/month you might have performance issues.
                    </p>
                    <p>
                        Similarly, at this stage we're optimized for customers running on a subscription model (mostly
                        SaaS). If you're running a business where your revenue is not coming from recurring payments,
                        you might find Revenue analytics to be less useful/more empty than expected.
                    </p>
                </LemonBanner>

                {sourceRunningForTheFirstTime && (
                    <LemonBanner
                        type="success"
                        dismissKey={`revenue-analytics-sync-in-progress-banner-${sourceRunningForTheFirstTime.id}`}
                        action={{ children: 'Refresh', onClick: () => window.location.reload() }}
                        className={cn(!newSceneLayout && 'mb-2')}
                    >
                        One of your revenue data warehouse sources is running for the first time. <br />
                        This means you might not see all of your revenue data yet. <br />
                        We display partial data - most recent months first - while the initial sync is running. <br />
                        Refresh the page to see the latest data.
                    </LemonBanner>
                )}

                <RevenueAnalyticsSceneContent />
            </SceneContent>
        </BindLogic>
    )
}

const RevenueAnalyticsSceneContent = (): JSX.Element => {
    const { hasRevenueTables, hasRevenueEvents } = useValues(revenueAnalyticsLogic)

    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    // Still loading from the server, so we'll show a spinner
    if (hasRevenueTables === null) {
        return <SpinnerOverlay sceneLevel />
    }

    // Hasn't connected any revenue sources or events yet, so we'll show the onboarding
    if (!hasRevenueTables && !hasRevenueEvents) {
        return <Onboarding />
    }

    return (
        <div className={cn('RevenueAnalyticsDashboard', newSceneLayout && '-mt-2')}>
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
