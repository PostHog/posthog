import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { InsightLogicProps } from '~/types'

import { dataRetentionBannerLogic } from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'
import { RetentionDeletionMessage } from 'products/product_analytics/frontend/insights/dataRetention/RetentionDeletionMessage'
import { QuillInsightBanner } from 'products/product_analytics/frontend/insights/shared/QuillInsightBanner'

import { insightRetentionBannerLogic } from './insightRetentionBannerLogic'

export function InsightRetentionBanner({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { shouldShowBanner } = useValues(insightRetentionBannerLogic(insightProps))
    const { dismiss } = useActions(dataRetentionBannerLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!shouldShowBanner) {
        return null
    }

    const message = <RetentionDeletionMessage subject="This insight includes events" />

    if (todayRailNav) {
        return (
            <QuillInsightBanner tone="warning" onClose={dismiss}>
                {message}
            </QuillInsightBanner>
        )
    }

    return (
        <LemonBanner type="warning" onClose={dismiss}>
            {message}
        </LemonBanner>
    )
}
