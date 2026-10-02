import { LemonButton } from '@posthog/lemon-ui'

import { colonDelimitedDuration } from 'lib/utils/durations'

import type { ScannerType } from '../replay_scanners/types'
import type { TimelineMarker } from '../utils/recordingTimeline'
import { scannerTypeIcon } from './ScannerTypeBadge'

/** One scan's key moment: which scanner flagged it and what it answered. */
export function TimelineMarkerChip({ marker, onClick }: { marker: TimelineMarker; onClick: () => void }): JSX.Element {
    const label = [marker.scannerName, marker.result].filter(Boolean).join(' · ')
    return (
        <LemonButton
            size="xsmall"
            type={marker.flagged ? 'primary' : 'secondary'}
            icon={marker.scannerType ? scannerTypeIcon(marker.scannerType as ScannerType) : undefined}
            onClick={(e) => {
                // A chip sits inside a chapter row, which seeks to the chapter's start on its own click.
                e.stopPropagation()
                onClick()
            }}
            tooltip={`${label} at ${colonDelimitedDuration(Math.floor(marker.timestampMs / 1000), null)}`}
            className="max-w-full"
            data-attr="vision-timeline-marker"
        >
            <span className="truncate font-normal">{label}</span>
        </LemonButton>
    )
}
