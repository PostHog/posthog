import type { MCPWrappedArchetypeCardApi } from '../../generated/api.schemas'
import { ARCHETYPE_NAMES, formatDuration, formatPercent } from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { ARCHETYPE_HOGGIES } from '../wrappedTheme'

function describe(card: MCPWrappedArchetypeCardApi): string {
    const evidence = card.evidence ?? 0
    switch (card.archetype) {
        case 'one_hit_wonder':
            return `One tool took ${formatPercent(evidence)} of all calls.`
        case 'swiss_army_knife':
            return `No single tool carried you. ${evidence} tools each took more than 5% of calls.`
        case 'night_owl':
            return `${formatPercent(evidence)} of calls came in between 10 pm and 6 am.`
        case 'weekend_warrior':
            return `${formatPercent(evidence)} of calls came in on weekends.`
        case 'speed_demon':
            return `95% of calls were answered in under ${formatDuration(evidence)}.`
        case 'rocket':
            return `Calls grew ${evidence}× from your first full month.`
        case 'all_rounder':
            return 'No single pattern stood out. Agents used a bit of everything.'
    }
}

export function ArchetypeCard({ card }: { card: MCPWrappedArchetypeCardApi }): JSX.Element {
    return (
        <WrappedCard cardKey="archetype" kicker="Your server's personality" hoggie={ARCHETYPE_HOGGIES[card.archetype]}>
            <h2 className="MCPWrapped__pop m-0 text-4xl font-bold leading-tight">{ARCHETYPE_NAMES[card.archetype]}</h2>
            <p className="MCPWrapped__rise m-0 text-base">{describe(card)}</p>
        </WrappedCard>
    )
}
