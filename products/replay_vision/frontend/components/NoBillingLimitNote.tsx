import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { formatCreditCount } from '../utils/credits'

interface Props {
    /** Projected monthly credits across every enabled scanner. */
    projectedCredits: number
    /** The total counts a scanner that isn't running yet, so the projection is conditional on enabling it. */
    draft?: boolean
}

/**
 * Uncapped orgs get no meter and no exhaustion guard, so the spend surfaces stand in for both:
 * the projection on its own line, then the same status-plus-way-out shape as `QuotaExhaustedNote`.
 */
export function NoBillingLimitNote({ projectedCredits, draft = false }: Props): JSX.Element {
    return (
        <div className="space-y-1 text-xs text-muted">
            <div>
                {draft
                    ? `With this scanner enabled, your scanners would use ~${formatCreditCount(
                          projectedCredits
                      )}/month.`
                    : `Enabled scanners are projected to use ~${formatCreditCount(projectedCredits)}/month.`}
            </div>
            {/* One colour throughout, so the link is underlined instead of accented to stay discoverable. */}
            <div className="text-danger">
                No billing limit set. Spend is uncapped.{' '}
                <Link className="text-danger underline" to={urls.organizationBilling([ProductKey.REPLAY_VISION])}>
                    Set a billing limit
                </Link>{' '}
                to control costs.
            </div>
        </div>
    )
}
