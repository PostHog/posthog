import { IconQuestion } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { SignalReportActionability } from '../../types'
import { ACTIONABILITY_PRESENTATION } from './actionabilityPresentation'

// Mirrors the LemonTag text color for each `type` (see LemonTag.scss; for these outlined types the
// text and border share the same var), so the overlaid help icon matches the tag's text.
const ACTIONABILITY_TEXT_COLOR: Record<SignalReportActionability, string> = {
    immediately_actionable: 'var(--success)',
    requires_human_input: 'var(--danger-lighter)',
    not_actionable: 'var(--color-text-secondary)',
}

export function SignalReportActionabilityBadge({
    actionability,
    explanation,
}: {
    actionability: SignalReportActionability | null | undefined
    /**
     * When set, a circled help icon overlays the tag's top-right corner and the rationale becomes the
     * tag's tooltip (replacing the generic category blurb). Absent, the tag shows the generic meaning.
     */
    explanation?: string | null
}): JSX.Element | null {
    if (actionability == null) {
        return null
    }

    const presentation = ACTIONABILITY_PRESENTATION[actionability]
    if (!presentation) {
        return null
    }

    const hasWhy = !!explanation?.trim()
    // Always trigger off the wrapping span (matching the priority badge), rather than handing the bare
    // LemonTag to Base UI as the trigger. When a rationale exists the help icon overlays the (rounded)
    // top-right corner and the tooltip carries the rationale; otherwise it's the generic category blurb.
    return (
        <Tooltip title={hasWhy ? explanation : presentation.tooltip}>
            <span className="relative inline-flex cursor-help">
                <LemonTag size="small" type={presentation.type} className="select-none">
                    {presentation.label}
                </LemonTag>
                {hasWhy && (
                    <IconQuestion
                        className="absolute right-0 top-0 size-3 -translate-y-1/2 translate-x-1/2 rounded-full bg-surface-primary"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ color: ACTIONABILITY_TEXT_COLOR[actionability] }}
                    />
                )}
            </span>
        </Tooltip>
    )
}
