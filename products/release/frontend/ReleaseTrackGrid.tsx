import { dayjs } from 'lib/dayjs'

import { Scale } from './releaseTracks'

export function ReleaseTrackGrid({ scale }: { scale: Scale }): JSX.Element {
    const { start, days, day: width } = scale
    const today = dayjs().startOf('day')
    return (
        <div className="pointer-events-none absolute inset-0">
            {Array.from({ length: days }, (_, index) => start.add(index, 'day')).map((day, index) =>
                day.day() === 0 || day.day() === 6 ? (
                    <div
                        key={index}
                        className="absolute inset-y-0 bg-fill-hover opacity-60"
                        style={{ left: index * width, width }}
                    />
                ) : null
            )}
            <div
                className="absolute inset-y-0 w-px bg-primary"
                style={{ left: today.diff(start, 'day') * width + width / 2 }}
            />
        </div>
    )
}
