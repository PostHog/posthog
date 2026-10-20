import { LemonBanner, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { BlastRadiusApi } from 'products/workflows/frontend/generated/api.schemas'

export interface RealtimeCohortAudienceNoticeProps {
    blastRadius: BlastRadiusApi | null | undefined
}

/** Explains why an audience that holds a realtime cohort takes no other conditions. */
export function RealtimeCohortAudienceNotice({ blastRadius }: RealtimeCohortAudienceNoticeProps): JSX.Element | null {
    if (blastRadius?.realtime_cohort || blastRadius?.realtime_cohort_with_other_conditions) {
        return (
            <LemonBanner type="info">
                Realtime cohorts can't be combined with other conditions. To narrow this audience,{' '}
                <Link
                    to={urls.cohort('new')}
                    // A new tab keeps an unsaved broadcast or workflow open.
                    target="_blank"
                    data-attr="workflows-realtime-cohort-create-cohort"
                >
                    create a cohort
                </Link>{' '}
                with the extra conditions.
            </LemonBanner>
        )
    }
    return null
}
