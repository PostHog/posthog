import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { billingLogic } from 'scenes/billing/billingLogic'
import { urls } from 'scenes/urls'

import { BillingType } from '~/types'

/** Ingestion products Vision depends on that are over their billing limit (data dropped at capture). */
export function ingestionLimits(billing: BillingType | null): { eventsLimited: boolean; recordingsLimited: boolean } {
    const overLimit = (usageKey: string): boolean =>
        !!billing?.products?.some((product) => product.usage_key === usageKey && product.percentage_usage > 1)
    return { eventsLimited: overLimit('events'), recordingsLimited: overLimit('recordings') }
}

export function IngestionLimitBanner(): JSX.Element | null {
    const { billing } = useValues(billingLogic)
    const { eventsLimited, recordingsLimited } = ingestionLimits(billing)

    if (!eventsLimited && !recordingsLimited) {
        return null
    }
    const message =
        eventsLimited && recordingsLimited
            ? 'Your organization is over its Product analytics and Session replay limits, so new events and recordings are being dropped. Scanners have nothing new to scan until the limits are raised.'
            : eventsLimited
              ? 'Your organization is over its Product analytics limit, so events are being dropped. New sessions arrive without event data, and scans of them will be marked ineligible.'
              : 'Your organization is over its Session replay limit, so new recordings are not being captured. Scanners have nothing new to scan until the limit is raised.'
    return (
        <LemonBanner type="warning">
            {message} <Link to={urls.organizationBilling()}>Manage billing limits</Link>
        </LemonBanner>
    )
}
