import { useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { dataRetentionBannerLogic } from './dataRetentionBannerLogic'

export function RetentionDeletionMessage({ subject }: { subject: string }): JSX.Element | null {
    const { retentionPeriodLabel, nextDeletionLabel } = useValues(dataRetentionBannerLogic)

    if (!retentionPeriodLabel || !nextDeletionLabel) {
        return null
    }

    return (
        <>
            <span>{`${subject} older than your ${retentionPeriodLabel} retention period. Those events will be deleted starting ${nextDeletionLabel}. Adjust your retention period in `}</span>
            <Link
                to={urls.settings('environment-product-analytics', 'project-events-retention')}
                data-attr="retention-deletion-settings"
            >
                Settings
            </Link>
            <span>.</span>
        </>
    )
}
