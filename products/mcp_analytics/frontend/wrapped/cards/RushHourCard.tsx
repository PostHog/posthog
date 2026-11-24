import { colors } from '@posthog/brand/colors'

import { cn } from 'lib/utils/css-classes'

import type { MCPWrappedRushHourCardApi } from '../../generated/api.schemas'
import { dayPart, formatHour, formatTimezone, peakMultiple, rushHourLine } from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { RUSH_HOUR_THEMES } from '../wrappedTheme'

const DAY_LABELS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
const HOUR_LABELS = ['12am', '6am', '12pm', '6pm']

export function RushHourCard({ card }: { card: MCPWrappedRushHourCardApi }): JSX.Element {
    const multiple = peakMultiple(card.heat)
    return (
        <WrappedCard
            cardKey="rush_hour"
            kicker="Rush hour"
            theme={RUSH_HOUR_THEMES[dayPart(card.hour, card.night_shift)]}
        >
            <h2 className="MCPWrapped__rise m-0 text-4xl font-bold leading-tight">
                {formatHour(card.weekday, card.hour)}
            </h2>
            <p className="MCPWrapped__rise m-0 text-base">
                <strong className="block">{rushHourLine(card.weekday, card.hour, card.night_shift)}</strong>
                {multiple && (
                    <>
                        <span className="MCPWrapped__mark">
                            {multiple.charAt(0).toUpperCase()}
                            {multiple.slice(1)}
                        </span>{' '}
                        more calls than your average hour.
                    </>
                )}
            </p>
            <div
                className="MCPWrapped__rise grid mt-2 grid-cols-[1.5rem_repeat(24,minmax(0,1fr))] gap-0.5 text-xs"
                aria-label="Calls by weekday and hour"
            >
                {DAY_LABELS.map((label, dayIndex) => (
                    <div key={label} className="contents">
                        <span className="self-center opacity-75">{label}</span>
                        {card.heat.slice(dayIndex * 24, dayIndex * 24 + 24).map((level, hour) => {
                            const isPeak = dayIndex === card.weekday - 1 && hour === card.hour
                            return (
                                <span
                                    key={hour}
                                    className={cn('aspect-square rounded-sm', isPeak && 'relative z-10 scale-125')}
                                    // The busiest hour takes the sunset's yellow, so it stands out from the white cells.
                                    style={{
                                        background: isPeak
                                            ? colors.yellow.core
                                            : `rgb(255 255 255 / ${0.08 + (level / 100) * 0.92})`,
                                    }}
                                />
                            )
                        })}
                    </div>
                ))}
                <span />
                {HOUR_LABELS.map((label) => (
                    <span key={label} className="col-span-6 pt-1 opacity-75">
                        {label}
                    </span>
                ))}
            </div>
            <p className="MCPWrapped__rise m-0 text-xs opacity-75">* Times in {formatTimezone(card.timezone)}</p>
        </WrappedCard>
    )
}
