import { dayjs } from 'lib/dayjs'

import { Scale } from './releaseTracks'

export function ReleaseTimelineAxis({ scale }: { scale: Scale }): JSX.Element {
    const { start, day: width } = scale
    const today = dayjs().startOf('day')
    const days = Array.from({ length: scale.days }, (_, index) => start.add(index, 'day'))
    const months = days.filter((day, index) => day.date() === 1 || (index === 0 && day.daysInMonth() - day.date() >= 4))
    return (
        <div className="relative h-12" style={{ width: scale.days * width }}>
            {months.map((month) => (
                <div
                    key={month.format('YYYY-MM-DD')}
                    className="absolute top-1.5 pl-2 text-[11px] font-semibold normal-case tracking-normal text-foreground"
                    style={{ left: month.diff(start, 'day') * width }}
                >
                    {month.format('MMMM YYYY')}
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
