import { IconHome, IconPlus } from '@posthog/icons'
import { LemonButton, Link, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { IntervalFilterStandalone } from 'lib/components/IntervalFilter'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { PipelineStage, ProductKey } from '~/types'

import { REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID, revenueAnalyticsLogic } from './revenueAnalyticsLogic'
import { GrossRevenueTile } from './tiles/GrossRevenueTile'
import { OverviewTile } from './tiles/OverviewTile'
import { RevenueGrowthRateTile } from './tiles/RevenueGrowthRateTile'
import { RevenueChurnTile } from './tiles/TopCustomers'

export const scene: SceneExport = {
    component: RevenueAnalyticsScene,
    logic: revenueAnalyticsLogic,
}

export function RevenueAnalyticsScene(): JSX.Element {
    const { hasRevenueTables } = useValues(revenueAnalyticsLogic)
    const { updateHasSeenProductIntroFor } = useActions(userLogic)

    return (
        <BindLogic logic={revenueAnalyticsLogic} props={{}}>
            <BindLogic logic={dataNodeCollectionLogic} props={{ key: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
                <ProductIntroduction
                    isEmpty={!hasRevenueTables}
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

                {hasRevenueTables && (
                    <div className="flex flex-col gap-2">
                        <RevenueAnalyticsFilters />
                        <RevenueAnalyticsTables />
                    </div>
                )}
            </BindLogic>
        </BindLogic>
    )
}

const RevenueAnalyticsFilters = (): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom, interval },
    } = useValues(revenueAnalyticsLogic)
    const { setDates, setInterval, resetDatesAndInterval } = useActions(revenueAnalyticsLogic)

    return (
        <div className="flex flex-row gap-1">
            <Tooltip title="Reset to default">
                <LemonButton icon={<IconHome />} onClick={resetDatesAndInterval} />
            </Tooltip>
            <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
            <IntervalFilterStandalone interval={interval} onIntervalChange={setInterval} />
            <ReloadAll iconOnly />
        </div>
    )
}

const RevenueAnalyticsTables = (): JSX.Element => {
    return (
        <div className="flex flex-col gap-4">
            <OverviewTile />

            <GrossRevenueTile />
            <RevenueGrowthRateTile />
            <RevenueChurnTile />
        </div>
    )
}
