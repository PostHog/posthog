import { LemonButton } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

import { revenueAnalyticsLogic } from './revenueAnalyticsLogic'

export const scene: SceneExport = {
    component: RevenueAnalyticsScene,
    logic: revenueAnalyticsLogic,
}

export function RevenueAnalyticsScene(): JSX.Element {
    return (
        <>
            <PageHeader buttons={<LemonButton type="primary">CREATE SOMETHING TODO</LemonButton>} delimited />
            <ProductIntroduction
                isEmpty // TODO: Compute whether people need to enable this or not
                productName="Revenue Analytics"
                productKey={ProductKey.REVENUE_ANALYTICS}
                thingName="revenue" // TODO: Doesn't make sense, this is temporary
                description="Track and analyze your revenue metrics to understand your business performance and growth."
                docsURL="https://posthog.com/docs/revenue-analytics"
                action={() => router.actions.push(urls.revenueAnalytics())} // TODO: Doesn't make sense, this is temporary
            />
        </>
    )
}
