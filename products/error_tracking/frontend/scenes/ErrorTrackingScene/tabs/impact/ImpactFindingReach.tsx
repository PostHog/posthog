import { Text } from 'lib/ui/quill'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { ImpactFinding } from './impactFindings'
import { findingReach } from './impactReach'
import { ImpactTicketLinks } from './ImpactTicketLinks'

export function ImpactFindingReach({ finding }: { finding: ImpactFinding }): JSX.Element {
    const { value, unit, detail, tickets } = findingReach(finding)
    return (
        <div className="flex flex-col">
            <Text render={<span />} size="sm" weight="semibold" className="tabular-nums">
                {humanFriendlyLargeNumber(value)}
            </Text>
            <Text render={<span />} size="xs" variant="muted">
                {unit}
            </Text>
            {detail && (
                <Text render={<span />} size="xs" variant="muted">
                    {detail}
                </Text>
            )}
            {tickets.length > 0 && <ImpactTicketLinks tickets={tickets} />}
        </div>
    )
}
