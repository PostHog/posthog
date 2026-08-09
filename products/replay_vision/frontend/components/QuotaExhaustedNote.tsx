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
    const [status, linkText, suffix] = onFreePlan
        ? ['Free credits used up.', 'Add billing', 'to keep scanning.']
        : ['Spend limit reached.', 'Raise your billing limit', 'to resume scanning.']
    return (
        <div className="text-xs text-danger">
            {status}{' '}
            <Link className="text-danger underline" to={urls.organizationBilling([ProductKey.REPLAY_VISION])}>
                {linkText}
            </Link>{' '}
            {suffix}
        </div>
    )
}
