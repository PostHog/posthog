import { Text } from 'lib/ui/quill'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { ImpactFinding } from './impactFindings'
import { findingReach } from './impactReach'
import { ImpactTicketLinks } from './ImpactTicketLinks'

// The reach in one line, for narrow layouts where the reach column is hidden.
export function ImpactFindingReachLine({ finding }: { finding: ImpactFinding }): JSX.Element {
    const { value, unit, detail, tickets } = findingReach(finding)
    return (
        <Text render={<span />} size="xs" variant="muted" className="tabular-nums">
            {[`${humanFriendlyLargeNumber(value)} ${unit}`, detail].filter(Boolean).join(', ')}
            {tickets.length > 0 && (
                <>
                    {' '}
                    <ImpactTicketLinks tickets={tickets} />
                </>
            )}
        </Text>
    )
}
