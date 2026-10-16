import { LemonBanner, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { BlastRadiusApi } from 'products/workflows/frontend/generated/api.schemas'

export interface RealtimeCohortAudienceNoticeProps {
    blastRadius: BlastRadiusApi | null | undefined
}

/** Explains why an audience that holds a realtime cohort takes no other conditions. */
export function RealtimeCohortAudienceNotice({ blastRadius }: RealtimeCohortAudienceNoticeProps): JSX.Element | null {
    const mixed = blastRadius?.realtime_cohort_with_other_conditions
    if (mixed) {
        return (
            <LemonBanner type="warning">
                Cohort <Link to={urls.cohort(mixed.id)}>{mixed.name}</Link> is a realtime cohort, so it has to be the
                only condition. Remove the other conditions, or add them to the cohort itself.
            </LemonBanner>
        )
    }
    if (blastRadius?.realtime_cohort) {
        return (
            <LemonBanner type="info">
                Realtime cohorts can't be combined with other conditions. To narrow this audience,{' '}
                <Link to={urls.cohort('new')} data-attr="workflows-realtime-cohort-create-cohort">
                    create a cohort
                </Link>{' '}
                with the extra conditions.
            </LemonBanner>
        )
    }
    return null
}
