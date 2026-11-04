import { LemonButton } from '@posthog/lemon-ui'

import { HealthFindingSeverityIcon } from './HealthFindingSeverityIcon'
import type { HealthPanelFinding } from './healthPanelFindings'
import { useHealthFindingReporting } from './useHealthFindingReporting'

export function HealthFindingListItem({
    finding,
    isSelected,
    onSelect,
}: {
    finding: HealthPanelFinding
    isSelected: boolean
    /** Returns whether the pick puts the detail of the finding on screen. */
    onSelect: () => boolean
}): JSX.Element {
    const { reportOpened } = useHealthFindingReporting({
        code: finding.code,
        subcode: finding.subcode ?? undefined,
        severity: finding.severity,
        reason: finding.reason ?? undefined,
    })

    return (
        <li>
            <LemonButton
                size="small"
                fullWidth
                active={isSelected}
                icon={<HealthFindingSeverityIcon severity={finding.severity} />}
                onClick={() => {
                    if (onSelect()) {
                        // pinned: insights count `why` as opening the detail of a finding
                        reportOpened('why')
                    }
                }}
                aria-current={isSelected ? 'true' : undefined}
                data-attr="experiment-health-finding"
            >
                <span className="font-semibold">{finding.title}</span>
            </LemonButton>
        </li>
    )
}
