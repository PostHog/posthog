import { IconLive, IconRewindPlay } from '@posthog/icons'

import { ErrorEventType } from 'lib/components/Errors/types'
import { Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

// The list query sets both flags on each row: `$has_recording` from the replay tables, `linkedLogs` from logs.
export function LinkedDataBadges({ record }: { record: ErrorEventType }): JSX.Element | null {
    const hasRecording = record.properties.$has_recording === true
    const hasLogs = record.linkedLogs === true

    if (!hasRecording && !hasLogs) {
        return null
    }

    return (
        <span className="inline-flex items-center gap-1 text-muted-foreground">
            {hasRecording && (
                <Tooltip>
                    <TooltipTrigger render={<span className="inline-flex" aria-label="Has a recording" />}>
                        <IconRewindPlay />
                    </TooltipTrigger>
                    <TooltipContent>Has a recording</TooltipContent>
                </Tooltip>
            )}
            {hasLogs && (
                <Tooltip>
                    <TooltipTrigger render={<span className="inline-flex" aria-label="Has linked logs" />}>
                        <IconLive />
                    </TooltipTrigger>
                    <TooltipContent>Has linked logs</TooltipContent>
                </Tooltip>
            )}
        </span>
    )
}
