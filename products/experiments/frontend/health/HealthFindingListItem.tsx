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
    onSelect: () => void
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
                    // The first issue shows without a click, so only a reader's own pick reports the finding as opened.
                    if (!isSelected) {
                        // pinned: `open_kind` value, kept from the "Why?" button that opened the detail before
                        reportOpened('why')
                    }
                    onSelect()
                }}
                aria-current={isSelected ? 'true' : undefined}
                data-attr="experiment-health-finding"
            >
                <span className="font-semibold">{finding.title}</span>
            </LemonButton>
        </li>
    )
}
