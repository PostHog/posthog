import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { formatCreditCount } from '../utils/credits'

interface Props {
    /** Projected monthly credits across every enabled scanner. */
    projectedCredits: number
}

/** Uncapped orgs get no meter and no exhaustion guard, so the spend surfaces point them at the billing limit. */
export function NoBillingLimitNote({ projectedCredits }: Props): JSX.Element {
    return (
        <div className={`text-xs ${projectedCredits > 0 ? 'text-warning' : 'text-muted'}`}>
            No billing limit set. Enabled scanners are projected to use ~{formatCreditCount(projectedCredits)}/month.{' '}
            <Link to={urls.organizationBilling([ProductKey.REPLAY_VISION])}>Set a billing limit</Link>
        </div>
    )
}
