import { IconRewindPlay } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { colonDelimitedDuration } from 'lib/utils/durations'

/** One cited moment: a seek control into the recording, or a plain timestamp where no player is on screen. */
export function TimestampCitation({
    timestampMs,
    onSeek,
}: {
    timestampMs: number
    onSeek?: (timestampMs: number) => void
}): JSX.Element {
    const label = colonDelimitedDuration(Math.max(0, Math.floor(timestampMs / 1000)), null)
    if (!onSeek) {
        return <span className="text-muted font-mono ml-0.5">{label}</span>
    }
    return (
        <Link onClick={() => onSeek(timestampMs)} className="ml-0.5" data-attr="vision-observation-citation">
            <IconRewindPlay className="inline-block align-text-bottom mr-0.5" />
            <span className="font-mono">{label}</span>
        </Link>
    )
}
