import type { MCPWrappedArchetypeCardApi, MCPWrappedCardsApi } from '../../generated/api.schemas'
import { ARCHETYPE_NAMES, ARCHETYPE_TAGLINES, formatDuration, formatPercent, personalityStats } from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { ARCHETYPE_HOGGIES } from '../wrappedTheme'

function describe(card: MCPWrappedArchetypeCardApi): string {
    const evidence = card.evidence ?? 0
    switch (card.archetype) {
        case 'one_hit_wonder':
            return `One tool handled ${formatPercent(evidence)} of all calls.`
        case 'swiss_army_knife':
            return `Agents spread their calls across ${evidence} tools, each with more than 5%.`
        case 'night_owl':
            return `${formatPercent(evidence)} of calls came in between 10 pm and 6 am.`
        case 'weekend_warrior':
            return `${formatPercent(evidence)} of calls came in on weekends.`
        case 'speed_demon':
            return `95% of tool calls returned in under ${formatDuration(evidence)}.`
        case 'rocket':
            return `Calls grew ${evidence}× since your first full month.`
        case 'all_rounder':
            return 'No single pattern stood out. Agents used a bit of everything.'
    }
}

export function ArchetypeCard({ cards }: { cards: MCPWrappedCardsApi }): JSX.Element {
    const card = cards.archetype
    return (
        <WrappedCard cardKey="archetype" kicker="Your server's personality" hoggie={ARCHETYPE_HOGGIES[card.archetype]}>
            <h2 className="MCPWrapped__pop m-0 text-4xl font-bold leading-tight">{ARCHETYPE_NAMES[card.archetype]}</h2>
            <p className="MCPWrapped__rise m-0 text-base">
                <strong className="block">{ARCHETYPE_TAGLINES[card.archetype]}</strong>
                {describe(card)}
            </p>
            <div className="MCPWrapped__rise mt-1 grid grid-cols-3 gap-2">
                {personalityStats(cards).map((stat) => (
                    <div key={stat.label} className="MCPWrapped__tile flex flex-col rounded-xl px-3 py-2.5">
                        <span className="text-xl font-bold tabular-nums">{stat.value}</span>
                        <span className="text-xs opacity-75">{stat.label}</span>
                    </div>
                ))}
            </div>
        </WrappedCard>
    )
}
