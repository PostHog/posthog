import { cn } from 'lib/utils/css-classes'

import type { MCPWrappedRushHourCardApi } from '../../generated/api.schemas'
import { formatHour, formatTimezone, peakMultiple, rushHourLine } from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { NIGHT_SHIFT_HOGGIE } from '../wrappedTheme'

const DAY_LABELS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
const HOUR_LABELS = ['12am', '6am', '12pm', '6pm']

export function RushHourCard({ card }: { card: MCPWrappedRushHourCardApi }): JSX.Element {
    const multiple = peakMultiple(card.heat)
    return (
        <WrappedCard
            cardKey="rush_hour"
            kicker={`Rush hour (${formatTimezone(card.timezone)})`}
            hoggie={card.night_shift ? NIGHT_SHIFT_HOGGIE : undefined}
        >
            <h2 className="MCPWrapped__rise m-0 text-4xl font-bold leading-tight">
                {formatHour(card.weekday, card.hour)}
            </h2>
            <p className="MCPWrapped__rise m-0 text-base font-bold">
                {rushHourLine(card.weekday, card.hour, card.night_shift)}
            </p>
            {multiple && (
                <div className="MCPWrapped__pop flex flex-wrap items-baseline gap-x-2">
                    <span className="text-4xl font-bold leading-none tabular-nums">{multiple}</span>
                    <span className="text-base">more calls than your average hour</span>
                </div>
            )}
            <div
                className="MCPWrapped__rise grid mt-2 grid-cols-[1.5rem_repeat(24,minmax(0,1fr))] gap-0.5 text-xs"
                aria-label="Calls by weekday and hour"
            >
                {DAY_LABELS.map((label, dayIndex) => (
                    <div key={label} className="contents">
                        <span className="self-center opacity-75">{label}</span>
                        {card.heat.slice(dayIndex * 24, dayIndex * 24 + 24).map((level, hour) => (
                            <span
                                key={hour}
                                className={cn(
                                    'aspect-square rounded-sm',
                                    dayIndex === card.weekday - 1 &&
                                        hour === card.hour &&
                                        'relative z-10 scale-125 ring-2 ring-white'
                                )}
                                style={{ background: `rgb(21 21 21 / ${0.06 + (level / 100) * 0.94})` }}
                            />
                        ))}
                    </div>
                ))}
                <span />
                {HOUR_LABELS.map((label) => (
                    <span key={label} className="col-span-6 pt-1 opacity-75">
                        {label}
                    </span>
                ))}
            </div>
        </WrappedCard>
    )
}
