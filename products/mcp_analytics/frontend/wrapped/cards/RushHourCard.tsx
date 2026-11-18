import type { MCPWrappedRushHourCardApi } from '../../generated/api.schemas'
import { formatHour } from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { NIGHT_SHIFT_HOGGIE } from '../wrappedTheme'

const DAY_LETTERS = ['M', 'T', 'W', 'T', 'F', 'S', 'S']

export function RushHourCard({ card }: { card: MCPWrappedRushHourCardApi }): JSX.Element {
    const detail = card.night_shift
        ? 'Agents did most of their calling at night.'
        : card.quiet_weekends
          ? 'Agents called most at this hour, and weekends were quiet.'
          : 'Agents called your server most at this hour.'
    return (
        <WrappedCard cardKey="rush_hour" kicker="Rush hour" hoggie={card.night_shift ? NIGHT_SHIFT_HOGGIE : undefined}>
            <h2 className="MCPWrapped__rise m-0 text-4xl font-bold leading-tight">
                {formatHour(card.weekday, card.hour)}
            </h2>
            <p className="MCPWrapped__rise m-0 text-base">
                {detail} Times are in {card.timezone}.
            </p>
            <div
                className="MCPWrapped__rise grid grid-cols-[1rem_repeat(24,minmax(0,1fr))] gap-0.5 font-mono text-[9px]"
                aria-label="Calls by weekday and hour"
            >
                {DAY_LETTERS.map((letter, dayIndex) => (
                    <div key={dayIndex} className="contents">
                        <span className="self-center opacity-75">{letter}</span>
                        {card.heat.slice(dayIndex * 24, dayIndex * 24 + 24).map((level, hour) => (
                            <span
                                key={hour}
                                className="aspect-square rounded-sm"
                                style={{ background: `rgb(21 21 21 / ${0.06 + (level / 100) * 0.94})` }}
                            />
                        ))}
                    </div>
                ))}
            </div>
        </WrappedCard>
    )
}
