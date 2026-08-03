import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

interface Props {
    /** False for orgs whose whole allocation is free: they have no limit to raise, they need billing at all. */
    canBeBilled: boolean
}

/** Shown once scanning has stopped, so the meter isn't a dead end. */
export function QuotaExhaustedNote({ canBeBilled }: Props): JSX.Element {
    const billing = urls.organizationBilling([ProductKey.REPLAY_VISION])
    // Muted so the link is the only accented element; the red status sits directly above.
    return (
        <div className="text-xs text-muted">
            {canBeBilled ? (
                <>
                    <Link to={billing}>Raise your billing limit</Link> to resume scanning.
                </>
            ) : (
                <>
                    <Link to={billing}>Add billing</Link> to keep scanning past the free credits.
                </>
            )}
        </div>
    )
}
