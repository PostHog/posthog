import { cn } from 'lib/utils/css-classes'

import type { ScannerType } from '../replay_scanners/types'
import type { TimelineMarker } from '../utils/recordingTimeline'
import { scannerTypeIcon } from './ScannerTypeBadge'

/** One scan's key moment on the rail: which scanner it came from and what it answered. */
export function TimelineKeyMoment({
    marker,
    onClick,
    className,
}: {
    marker: TimelineMarker
    onClick: () => void
    className?: string
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className={cn(
                'inline-flex items-center gap-1.5 min-w-0 max-w-full text-left cursor-pointer rounded border bg-surface-primary px-1.5 py-0.5 hover:bg-surface-secondary',
                marker.flagged ? 'border-accent' : 'border-primary',
                className
            )}
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
