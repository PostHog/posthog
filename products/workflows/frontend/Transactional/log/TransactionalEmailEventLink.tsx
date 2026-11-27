import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function TransactionalEmailEventLink({ uuid, at }: { uuid: string | null; at: string }): JSX.Element | null {
    return uuid ? (
        <Link to={urls.event(uuid, at)} className="text-xs shrink-0" data-attr="transactional-email-outcome-event">
            View event
        </Link>
    ) : null
}
