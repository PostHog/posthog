import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { InsightLogicProps } from '~/types'

import {
    CHANGE_RETENTION_ACTION,
    dataRetentionBannerLogic,
} from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'

import { insightRetentionBannerLogic } from './insightRetentionBannerLogic'

export function InsightRetentionBanner({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { shouldShowBanner, shouldShowDeletionBanner } = useValues(insightRetentionBannerLogic(insightProps))
    const { retentionPeriodLabel, retentionBannerAction, nextDeletionLabel, deletionCutoffLabel } =
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

    if (shouldShowDeletionBanner && deletionCutoffLabel && nextDeletionLabel) {
        return (
            <LemonBanner
                type="warning"
                onClose={snooze}
                action={{ ...CHANGE_RETENTION_ACTION, 'data-attr': 'insight-retention-deletion-change-retention' }}
            >
                {`This insight's date range goes back before ${deletionCutoffLabel}. Events before that date will be deleted on ${nextDeletionLabel}.`}
            </LemonBanner>
        )
    }

    return null
}
