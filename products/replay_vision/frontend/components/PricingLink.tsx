import { Link } from '@posthog/lemon-ui'

import { creditsToUsd, formatCreditCount } from '../utils/credits'

const VISION_PRICING_URL = 'https://posthog.com/replay-vision/pricing'

/** Pricing link for replay vision surfaces. Opens in a new tab so nobody loses a half-configured scanner. */
function VisionPricingLink({ dataAttr, children }: { dataAttr: string; children: React.ReactNode }): JSX.Element {
    return (
        <Link to={VISION_PRICING_URL} target="_blank" data-attr={dataAttr}>
            {children}
        </Link>
    )
}

/**
 * The credit-to-dollar rate, for surfaces that price something in credits.
 *
 * Credits are the unit we bill, so credits are what the numbers use, but the rate means nothing to someone who
 * hasn't already looked it up. The inline dollar equivalent next to a total only renders for orgs that can be
 * billed, so free-plan orgs have no other way to read a credit figure as money.
 */
export function CreditPriceNote({ dataAttr }: { dataAttr: string }): JSX.Element {
    return (
        <span>
            {formatCreditCount(1)} is {creditsToUsd(1)}.{' '}
            <VisionPricingLink dataAttr={dataAttr}>Read more about pricing</VisionPricingLink>
        </span>
    )
}
