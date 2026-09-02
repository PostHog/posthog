import { useMountedLogic, useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { billingLogic } from 'scenes/billing/billingLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { visionQuotaLogic } from '../logics/visionQuotaLogic'

export function IngestionLimitBanner(): JSX.Element | null {
    // visionQuotaLogic triggers the billing load; billingLogic doesn't self-load on mount.
    useMountedLogic(visionQuotaLogic)
    const { isProductAtOrOverUsageLimit } = useValues(billingLogic)

    const eventsLimited = isProductAtOrOverUsageLimit(ProductKey.PRODUCT_ANALYTICS)
    const recordingsLimited = isProductAtOrOverUsageLimit(ProductKey.SESSION_REPLAY)
    if (!eventsLimited && !recordingsLimited) {
        return null
    }
    const message =
        eventsLimited && recordingsLimited
            ? 'Your organization has reached its Product analytics and Session replay limits, so new events and recordings may not be captured. Scanners may have nothing new to scan until the limits are raised.'
            : eventsLimited
              ? 'Your organization has reached its Product analytics limit, so new events may not be captured. Sessions without event data are marked ineligible when scanned.'
              : 'Your organization has reached its Session replay limit, so new recordings may not be captured. Scanners may have nothing new to scan until the limit is raised.'
    return (
        <LemonBanner type="warning">
            {message} <Link to={urls.organizationBilling()}>Manage billing limits</Link>
        </LemonBanner>
    )
}
