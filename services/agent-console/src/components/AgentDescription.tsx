/**
 * One-line truncated agent description with a tooltip that reveals
 * the full text on hover. Shared between Classic and Studio so the
 * header chrome behaves identically.
 */

'use client'

import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

interface AgentDescriptionProps {
    description: string | null | undefined
}

export function AgentDescription({ description }: AgentDescriptionProps): React.ReactElement | null {
    const text = description?.trim() ?? ''
    if (!text) {
        return null
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<p className="truncate text-sm text-muted-foreground" />}>{text}</TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-md whitespace-pre-wrap text-xs">
                {text}
            </TooltipContent>
        </Tooltip>
    )
}
