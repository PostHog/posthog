import { cn } from 'lib/utils/css-classes'

import type { ScannerType } from '../replay_scanners/types'
import type { TimelineMarker } from '../utils/recordingTimeline'
import { scannerTypeIcon } from './ScannerTypeBadge'

/** One scan's key moment on the rail: which scanner it came from and what it answered. */
export function TimelineKeyMoment({ marker, onClick }: { marker: TimelineMarker; onClick: () => void }): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className="flex items-center gap-1.5 min-w-0 w-full text-left cursor-pointer rounded px-1 -mx-1 hover:bg-surface-secondary"
            data-attr="vision-timeline-marker"
        >
            {marker.scannerType && (
                <span className="flex shrink-0 text-secondary">
                    {scannerTypeIcon(marker.scannerType as ScannerType)}
                </span>
            )}
            <span className="text-sm truncate">{marker.scannerName}</span>
            {marker.result && (
                <span
                    className={cn('text-xs shrink-0', marker.flagged ? 'text-accent font-semibold' : 'text-secondary')}
                >
                    {marker.result}
                </span>
            )}
        </button>
    )
}
