import { IconQuestion } from '@posthog/icons'
import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { SignalReportActionability } from '../../types'
import { quillBadgeVariant } from '../detail/quillBadgeVariant'
import { ACTIONABILITY_PRESENTATION } from './actionabilityPresentation'

/**
 * The quill sibling of `SignalReportActionabilityBadge`. With a rationale, a help icon ends the badge
 * and the rationale replaces the generic category blurb in the tooltip.
 */
export function QuillSignalReportActionabilityBadge({
    actionability,
    explanation,
}: {
    actionability: SignalReportActionability | null | undefined
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
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Badge
                        variant={quillBadgeVariant(presentation.type)}
                        tabIndex={0}
                        className="cursor-help select-none"
                    />
                }
            >
                {presentation.label}
                {hasWhy && <IconQuestion className="size-3" />}
            </TooltipTrigger>
            <TooltipContent className="max-w-80">{hasWhy ? explanation : presentation.tooltip}</TooltipContent>
        </Tooltip>
    )
}
