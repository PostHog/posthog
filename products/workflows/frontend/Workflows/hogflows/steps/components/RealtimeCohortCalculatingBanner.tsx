import { LemonBanner, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { RealtimeCohortStatusApi } from 'products/workflows/frontend/generated/api.schemas'

import { isRealtimeCohortCalculating } from '../realtimeCohortStatus'

export interface RealtimeCohortCalculatingBannerProps {
    /** The audience's realtime cohort, when the audience is one. */
    status: RealtimeCohortStatusApi | null | undefined
}

export function RealtimeCohortCalculatingBanner({ status }: RealtimeCohortCalculatingBannerProps): JSX.Element | null {
    if (!status) {
        return null
    }
    const cohort = <Link to={urls.cohort(status.id)}>{status.name}</Link>
    if (isRealtimeCohortCalculating(status)) {
        return (
            <LemonBanner type="info">
                Cohort {cohort} is still calculating
                {/* Its own element, so page translation can't detach the text that each status refresh changes. */}
                {status.percent_complete != null ? <span> ({status.percent_complete}% done)</span> : null}. This send
                waits for it and starts on its own once it's ready.
            </LemonBanner>
        )
    }
    if (status.state === 'needs_attention') {
        return (
            <LemonBanner type="warning">
                Cohort {cohort} has a problem calculating, so this send can't start. Open the cohort to check it.
            </LemonBanner>
        )
    }
    return null
}
