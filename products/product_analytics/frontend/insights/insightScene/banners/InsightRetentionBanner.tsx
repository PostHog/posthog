import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { InsightLogicProps } from '~/types'

import { dataRetentionBannerLogic } from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'
import { QuillInsightBanner } from 'products/product_analytics/frontend/insights/shared/QuillInsightBanner'

import { insightRetentionBannerLogic } from './insightRetentionBannerLogic'

export function InsightRetentionBanner({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { shouldShowBanner } = useValues(insightRetentionBannerLogic(insightProps))
    const { retentionPeriodLabel, retentionBannerAction, nextDeletionLabel } = useValues(dataRetentionBannerLogic)
    const { dismiss } = useActions(dataRetentionBannerLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!shouldShowBanner || !retentionPeriodLabel) {
        return null
    }

    const message = (
        <>
            <span>
                This insight's date range goes beyond your {retentionPeriodLabel} data retention, so events older than
                that aren't included.
            </span>
            {nextDeletionLabel && <span>{` Those events will be deleted starting ${nextDeletionLabel}.`}</span>}
        </>
    )

    if (todayRailNav) {
        return (
            <QuillInsightBanner tone="warning" onClose={dismiss} action={retentionBannerAction ?? undefined}>
                {message}
            </QuillInsightBanner>
        )
    }

    return (
        <LemonBanner type="warning" onClose={dismiss} action={retentionBannerAction ?? undefined}>
            {message}
        </LemonBanner>
    )
}
