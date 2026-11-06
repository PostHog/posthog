import { LemonBanner, Link } from '@posthog/lemon-ui'

import { Dayjs, dayjs } from 'lib/dayjs'

import { overlapsEmailMetricsIncident } from './emailMetricsIncident'

export function EmailMetricsIncidentBanner({
    dateFrom,
    dateTo = dayjs(),
}: {
    dateFrom: Dayjs
    dateTo?: Dayjs
}): JSX.Element | null {
    if (!overlapsEmailMetricsIncident(dateFrom, dateTo)) {
        return null
    }

    return (
        <LemonBanner type="warning">
            Email metrics for Nov 3, 2026, 10:58-11:36 UTC are inflated because of an incident.{' '}
            <Link
                to="https://www.posthogstatus.com/incidents/q6dk441s"
                target="_blank"
                data-attr="workflows-email-metrics-incident-link"
            >
                See what happened
            </Link>
        </LemonBanner>
    )
}
