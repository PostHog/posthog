import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'

import { InsightLogicProps } from '~/types'

import {
    RETENTION_SETTINGS_URL,
    dataRetentionBannerLogic,
} from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'

import { insightRetentionBannerLogic } from './insightRetentionBannerLogic'

export function InsightRetentionBanner({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { shouldShowBanner, shouldShowDeletionBanner } = useValues(insightRetentionBannerLogic(insightProps))
    const { retentionPeriodLabel, retentionBannerAction, nextDeletionLabel, projectPeriodLabel } =
        useValues(dataRetentionBannerLogic)
    const { snooze } = useActions(dataRetentionBannerLogic)

    if (shouldShowBanner && retentionPeriodLabel) {
        return (
            <LemonBanner type="warning" onClose={snooze} action={retentionBannerAction ?? undefined}>
                This insight's date range goes beyond your {retentionPeriodLabel} data retention, so events older than
                that aren't included.
                {nextDeletionLabel && <span>{` Those events will be deleted starting ${nextDeletionLabel}.`}</span>}
            </LemonBanner>
        )
    }

    if (shouldShowDeletionBanner && projectPeriodLabel) {
        return (
            <LemonBanner type="warning" onClose={snooze}>
                <span>{`Events in this insight are older than your ${projectPeriodLabel} retention period and may be deleted soon. Adjust your retention period in `}</span>
                <Link to={RETENTION_SETTINGS_URL} data-attr="insight-retention-deletion-settings">
                    Settings
                </Link>
                <span>.</span>
            </LemonBanner>
        )
    }

    return null
}
