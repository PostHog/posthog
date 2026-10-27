import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { dataRetentionBannerLogic } from 'scenes/insights/dataRetention/dataRetentionBannerLogic'

import { InsightLogicProps } from '~/types'

import { insightRetentionBannerLogic } from './insightRetentionBannerLogic'

export function InsightRetentionBanner({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { shouldShowBanner } = useValues(insightRetentionBannerLogic(insightProps))
    const { retentionPeriodLabel, retentionBannerAction } = useValues(dataRetentionBannerLogic)
    const { snooze } = useActions(dataRetentionBannerLogic)

    if (!shouldShowBanner || !retentionPeriodLabel) {
        return null
    }

    return (
        <LemonBanner type="warning" onClose={snooze} action={retentionBannerAction}>
            This insight's date range goes beyond your {retentionPeriodLabel} data retention, so events older than that
            aren't included.
        </LemonBanner>
    )
}
