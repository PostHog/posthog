import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, Link, SpinnerOverlay } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { PipelineStage, ProductKey } from '~/types'

import { RevenueAnalyticsFilters } from './RevenueAnalyticsFilters'
import { REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID, revenueAnalyticsLogic } from './revenueAnalyticsLogic'
import { revenueEventsSettingsLogic } from './settings/revenueEventsSettingsLogic'
import { GrossRevenueTile } from './tiles/GrossRevenueTile'
import { OverviewTile } from './tiles/OverviewTile'
import { RevenueGrowthRateTile } from './tiles/RevenueGrowthRateTile'
import { TopCustomersTile } from './tiles/TopCustomersTile'

export const scene: SceneExport = {
    component: RevenueAnalyticsScene,
    logic: revenueAnalyticsLogic,
}

export function RevenueAnalyticsScene(): JSX.Element {
    return (
        <BindLogic logic={revenueEventsSettingsLogic} props={{}}>
            <BindLogic logic={revenueAnalyticsLogic} props={{}}>
                <BindLogic logic={dataNodeCollectionLogic} props={{ key: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
                    <RevenueAnalyticsSceneContent />
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

export function RevenueAnalyticsSceneContent(): JSX.Element {
    const { hasRevenueTables } = useValues(revenueAnalyticsLogic)
    const { mobileLayout } = useValues(navigationLogic)
    const { updateHasSeenProductIntroFor } = useActions(userLogic)

    if (hasRevenueTables === null) {
        return <SpinnerOverlay sceneLevel />
    }

    if (!hasRevenueTables) {
        return (
            <ProductIntroduction
                isEmpty
                productName="Revenue Analytics"
                productKey={ProductKey.REVENUE_ANALYTICS}
                titleOverride="Connect your first revenue source"
                thingName="revenue" // Not used because we're overriding the title, but required prop
                description="Track and analyze your revenue metrics to understand your business performance and growth."
                actionElementOverride={
                    <div className="flex flex-col gap-1">
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            onClick={() => {
                                updateHasSeenProductIntroFor(ProductKey.REVENUE_ANALYTICS, true)
                                router.actions.push(urls.pipelineNodeNew(PipelineStage.Source, { kind: 'stripe' }))
                            }}
                            data-attr="create-revenue-source"
                        >
                            Connect revenue source
                        </LemonButton>
                        <span className="text-xs text-muted-alt">
                            Only Stripe is supported currently. <br />
                            <Link
                                target="_blank"
                                to="https://github.com/PostHog/posthog/issues/new?assignees=&labels=enhancement,feature/revenue-analytics%2C+feature&projects=&template=feature_request.yml&title=New%20revenue%20source:%20%3Cinsert%20source%3E"
                            >
                                Request more revenue integrations.
                            </Link>
                        </span>
                    </div>
                }
            />
        )
    }

    return (
        <div>
            <LemonBanner
                type="info"
                dismissKey="revenue-analytics-beta"
                className="mb-2"
                action={{ children: 'Send feedback', id: 'revenue-analytics-feedback-button' }}
            >
                Revenue Analytics is in beta. Please let us know what you'd like to see here and/or report any issues
                directly to us!
            </LemonBanner>
            <div
                className={cn(
                    'sticky z-20 bg-primary border-b py-2',
                    mobileLayout ? 'top-[var(--breadcrumbs-height-full)]' : 'top-[var(--breadcrumbs-height-compact)]'
                )}
            >
                <RevenueAnalyticsFilters />
            </div>

            <RevenueAnalyticsTables />
        </div>
    )
}

const RevenueAnalyticsTables = (): JSX.Element => {
    return (
        <div className="flex flex-col gap-4">
            <OverviewTile />
            <GrossRevenueTile />

            <LemonDivider className="mt-6" />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <RevenueGrowthRateTile />
                <TopCustomersTile />
            </div>
        </div>
    )
}
