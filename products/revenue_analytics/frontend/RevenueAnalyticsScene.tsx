import { IconDatabase, IconPieChart, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, Link, SpinnerOverlay } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { PipelineStage, ProductKey, SidePanelTab } from '~/types'

import { RevenueAnalyticsFilters } from './RevenueAnalyticsFilters'
import { REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID, revenueAnalyticsLogic } from './revenueAnalyticsLogic'
import { revenueAnalyticsSettingsLogic } from './settings/revenueAnalyticsSettingsLogic'
import { CustomerCountTile, OverviewTile, RevenueTile, RevenueGrowthRateTile, TopCustomersTile } from './tiles'

export const scene: SceneExport = {
    component: RevenueAnalyticsScene,
    logic: revenueAnalyticsLogic,
    settingSectionId: 'environment-revenue-analytics',
}

const PRODUCT_NAME = 'Revenue Analytics'
const PRODUCT_KEY = ProductKey.REVENUE_ANALYTICS
const PRODUCT_DESCRIPTION = 'Track and analyze your revenue metrics to understand your business performance and growth.'
const PRODUCT_THING_NAME = 'revenue'

export function RevenueAnalyticsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { dataWarehouseSources } = useValues(revenueAnalyticsSettingsLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    if (!featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS]) {
        return (
            <ProductIntroduction
                isEmpty
                productName={PRODUCT_NAME}
                productKey={PRODUCT_KEY}
                thingName={PRODUCT_THING_NAME}
                description={
                    PRODUCT_DESCRIPTION +
                    ". Because we're in open beta, each user will need to enable this feature separately."
                }
                titleOverride="Revenue Analytics is in opt-in beta."
                actionElementOverride={
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={() => {
                            openSidePanel(SidePanelTab.FeaturePreviews, FEATURE_FLAGS.REVENUE_ANALYTICS)
                        }}
                        data-attr="activate-revenue-analytics"
                    >
                        Activate Revenue Analytics
                    </LemonButton>
                }
            />
        )
    }

    // Wait before binding/mounting the logics until we've finished loading the data warehouse sources
    if (dataWarehouseSources === null) {
        return <SpinnerOverlay sceneLevel />
    }

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <RevenueAnalyticsSceneContent />
        </BindLogic>
    )
}

const RevenueAnalyticsSceneContent = (): JSX.Element => {
    const { hasRevenueTables, hasRevenueEvents, revenueEnabledDataWarehouseSources } = useValues(revenueAnalyticsLogic)

    // Still loading from the server, so we'll show a spinner
    if (hasRevenueTables === null) {
        return <SpinnerOverlay sceneLevel />
    }

    // Hasn't connected any revenue sources or events yet, so we'll show the onboarding
    if (!hasRevenueTables && !hasRevenueEvents) {
        return <RevenueAnalyticsSceneOnboarding />
    }

    const sourceRunningForTheFirstTime = revenueEnabledDataWarehouseSources?.find(
        (source) => source.status === 'Running' && !source.last_run_at
    )

    return (
        <div className="RevenueAnalyticsDashboard">
            <LemonBanner
                type="info"
                dismissKey="revenue-analytics-beta-banner"
                className="mb-2"
                action={{ children: 'Send feedback', id: 'revenue-analytics-feedback-button' }}
            >
                Revenue Analytics is in beta. Please let us know what you'd like to see here and/or report any issues
                directly to us!
            </LemonBanner>

            <LemonBanner type="warning" dismissKey="revenue-analytics-deferred-revenue-banner" className="mb-2">
                <b>We've made some updates!</b>
                <br />
                We've recently introduced deferred revenue recognition for data warehouse sources. This means you will
                see revenue in the future if you've created an invoice item with a <code>period.start</code> and{' '}
                <code>period.end</code> that spans several months.
                <br />
                More information on{' '}
                <Link to="https://posthog.com/docs/web-analytics/revenue-analytics#deferred-revenue">our docs</Link>.
            </LemonBanner>

            {sourceRunningForTheFirstTime && (
                <LemonBanner
                    type="success"
                    className="mb-2"
                    dismissKey={`revenue-analytics-sync-in-progress-banner-${sourceRunningForTheFirstTime.id}`}
                    action={{ children: 'Refresh', onClick: () => window.location.reload() }}
                >
                    One of your revenue data warehouse sources is running for the first time. <br />
                    This means you might not see all of your revenue data yet. <br />
                    We display partial data - most recent months first - while the initial sync is running. <br />
                    Refresh the page to see the latest data.
                </LemonBanner>
            )}

            <RevenueAnalyticsFilters />
            <RevenueAnalyticsTables />
        </div>
    )
}

const RevenueAnalyticsSceneOnboarding = (): JSX.Element => {
    const { updateHasSeenProductIntroFor } = useActions(userLogic)

    return (
        <ProductIntroduction
            isEmpty
            productName={PRODUCT_NAME}
            productKey={PRODUCT_KEY}
            thingName={PRODUCT_THING_NAME} // Not used because we're overriding the title, but required prop
            description={PRODUCT_DESCRIPTION}
            titleOverride="Connect your first revenue source or event"
            actionElementOverride={
                <div className="flex flex-col gap-2">
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        sideIcon={<IconPieChart />}
                        onClick={() => {
                            updateHasSeenProductIntroFor(ProductKey.REVENUE_ANALYTICS, true)
                            router.actions.push(urls.revenueSettings())
                        }}
                        data-attr="create-revenue-event"
                    >
                        Connect revenue event
                    </LemonButton>
                    <div className="flex flex-col gap-1">
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            sideIcon={<IconDatabase />}
                            onClick={() => {
                                updateHasSeenProductIntroFor(ProductKey.REVENUE_ANALYTICS, true)
                                router.actions.push(urls.pipelineNodeNew(PipelineStage.Source, { source: 'Stripe' }))
                            }}
                            data-attr="create-revenue-source"
                        >
                            Connect revenue source
                        </LemonButton>
                        <span className="text-xs text-muted-alt">
                            Stripe is the only revenue source supported currently. <br />
                            <Link
                                target="_blank"
                                to="https://github.com/PostHog/posthog/issues/new?assignees=&labels=enhancement,feature/revenue-analytics%2C+feature&projects=&template=feature_request.yml&title=New%20revenue%20source:%20%3Cinsert%20source%3E"
                            >
                                Request more revenue integrations.
                            </Link>
                        </span>
                    </div>
                </div>
            }
        />
    )
}

const RevenueAnalyticsTables = (): JSX.Element => {
    return (
        <div className="flex flex-col gap-4 mt-4">
            <OverviewTile />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="col-span-2">
                    <RevenueTile />
                </div>
                <div className="col-span-2">
                    <CustomerCountTile />
                </div>

                <div className="col-span-1">
                    <RevenueGrowthRateTile />
                </div>
                <div className="col-span-1">
                    <TopCustomersTile />
                </div>
            </div>
        </div>
    )
}
