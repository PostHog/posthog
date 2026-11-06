import { IconRewindPlay } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { colonDelimitedDuration } from 'lib/utils/durations'

/** One cited moment: a seek control into the recording, or a plain timestamp where no player is on screen. */
export function QuillTimestampCitation({
    timestampMs,
    onSeek,
}: {
    timestampMs: number
    onSeek?: (timestampMs: number) => void
}): JSX.Element {
    const label = colonDelimitedDuration(Math.max(0, Math.floor(timestampMs / 1000)), null)
    if (!onSeek) {
        return <span className="text-muted-foreground font-mono ml-0.5">{label}</span>
    }
    return (
        <Button
            variant="link"
            size="inline"
            className="ml-0.5 align-baseline"
            onClick={() => onSeek(timestampMs)}
            data-attr="vision-observation-citation"
        >
            <IconRewindPlay className="inline-block align-text-bottom" />
            <span className="font-mono">{label}</span>
        </Button>
    )
}
