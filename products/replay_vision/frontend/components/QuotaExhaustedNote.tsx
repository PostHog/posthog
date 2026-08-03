import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

interface Props {
    /** Free-plan orgs have no limit to raise; they need billing in the first place. */
    onFreePlan: boolean
}

/**
 * Status and the way out in one line, shown once scanning has stopped.
 * Replaces `QuotaStatusLine` in that state rather than sitting under it.
 */
export function QuotaExhaustedNote({ onFreePlan }: Props): JSX.Element {
    const billing = urls.organizationBilling([ProductKey.REPLAY_VISION])
    return (
        <div className="text-xs text-danger">
            {onFreePlan ? 'Free credits used up.' : 'Spend limit reached.'}{' '}
            {onFreePlan ? (
                <>
                    <Link className="text-danger" to={billing}>
                        Add billing
                    </Link>{' '}
                    to keep scanning.
                </>
            ) : (
                <>
                    <Link className="text-danger" to={billing}>
                        Raise your billing limit
                    </Link>{' '}
                    to resume scanning.
                </>
            )}
        </div>
    )
}
