// PROTOTYPE (branch prototype/sending-limits-ux): the route to ask for more, which every variant keeps.
// Never merge.
import { Link } from '@posthog/lemon-ui'

export function AskForMore({
    lead = 'Need it sooner, for example for a migration with a deadline?',
}: {
    lead?: string
}): JSX.Element {
    return (
        <span>
            {lead} {/* pinned: data-attr of today's request link, which autocapture dashboards count */}
            <Link data-attr="workflows-request-sending-tier-increase">Ask for a higher allowance</Link>.
        </span>
    )
}
