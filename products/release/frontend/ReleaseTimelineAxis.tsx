import { dayjs } from 'lib/dayjs'

import { Scale } from './releaseTracks'

const MONTH_LABEL_ROOM = 96

export function ReleaseTimelineAxis({ scale, stickyOffset = 0 }: { scale: Scale; stickyOffset?: number }): JSX.Element {
    const { start, day: width } = scale
    const today = dayjs().startOf('day')
    const days = Array.from({ length: scale.days }, (_, index) => start.add(index, 'day'))
    const starts = days.flatMap((day, index) => (index === 0 || day.date() === 1 ? [index] : []))
    const months = starts.map((from, position) => ({ from, to: starts[position + 1] ?? days.length }))
    return (
        <div className="relative h-12" style={{ width: scale.days * width }}>
            {months.map(({ from, to }) => (
                <div
                    key={from}
                    className="absolute inset-y-0"
                    style={{ left: from * width, width: (to - from) * width, clipPath: 'inset(0)' }}
                >
                    {(to - from) * width >= MONTH_LABEL_ROOM && (
                        <div
                            className="sticky top-1.5 inline-block pl-2 pt-1.5 text-[11px] font-semibold normal-case tracking-normal whitespace-nowrap text-foreground"
                            style={{ left: stickyOffset }}
                        >
                            {days[from].format('MMMM YYYY')}
                        </div>
                    )}
                </div>
            ))}
            {days.map((day, index) =>
                width >= 22 || day.day() === 1 || day.isSame(today, 'day') ? (
                    <div
                        key={index}
                        className="absolute bottom-1.5 flex justify-center text-[11px] font-medium normal-case leading-5 tracking-normal tabular-nums"
                        style={{ left: index * width + width / 2 - 15, width: 30 }}
                    >
                        {day.isSame(today, 'day') ? (
                            <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 font-semibold text-primary-foreground">
                                {day.date()}
                            </span>
                        ) : (
                            <span
                                className={
                                    day.day() === 0 || day.day() === 6
                                        ? 'text-muted-foreground opacity-60'
                                        : 'text-muted-foreground'
                                }
                            >
                                {day.date()}
                            </span>
                        )}
                    </div>
                ) : null
            )}
        </div>
    )
}
