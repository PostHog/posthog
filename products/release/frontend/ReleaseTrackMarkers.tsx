import { dayjs } from 'lib/dayjs'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { Scale, x } from './releaseTracks'
import { ReleaseEvent } from './releaseUtils'

const MARKER_LABEL_WIDTH = 176
const MARKER_GUTTER = 28
const MIN_MARKER_LABEL = 24

export function ReleaseTrackMarkers({
    events,
    scale,
    top,
}: {
    events: ReleaseEvent[]
    scale: Scale
    top: number
}): JSX.Element {
    const { start } = scale
    const end = start.add(scale.days, 'day')
    const shown = events
        .filter(
            (event) =>
                (event.upcoming || event.kind === 'broadcast') &&
                !dayjs(event.date).isBefore(start) &&
                dayjs(event.date).isBefore(end)
        )
        .sort((a, b) => a.date.localeCompare(b.date))
    return (
        <>
            {shown.map((event, index) => {
                const next = shown[index + 1]
                const room = next ? x(next.date, scale) - x(event.date, scale) - MARKER_GUTTER : MARKER_LABEL_WIDTH
                return (
                    <div
                        key={event.key}
                        title={`${dayjs(event.date).format('D MMM')}: ${event.title}${event.detail ? ` (${event.detail})` : ''}`}
                        className="absolute flex h-4 items-center gap-1 whitespace-nowrap text-[11px] font-medium text-muted-foreground"
                        style={{ left: x(event.date, scale) + scale.day / 2 - 6, top }}
                        data-attr="release-timeline-marker"
                    >
                        {event.kind === 'broadcast' ? (
                            <span className="flex size-4 items-center justify-center rounded-sm bg-background text-foreground [&_svg]:size-3">
                                {iconForType('broadcasts')}
                            </span>
                        ) : (
                            <span className="size-2.5 rotate-45 border-2 border-primary bg-background" />
                        )}
                        {room >= MIN_MARKER_LABEL && (
                            <span className="truncate" style={{ maxWidth: Math.min(room, MARKER_LABEL_WIDTH) }}>
                                {event.kind === 'broadcast' ? event.title.split(':')[0] : event.title}
                            </span>
                        )}
                    </div>
                )
            })}
        </>
    )
}
