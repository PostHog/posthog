import type { MCPWrappedArchetypeCardApi } from '../../generated/api.schemas'
import { ARCHETYPE_NAMES, ARCHETYPE_TAGLINES, formatDuration, formatPercent } from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { ARCHETYPE_HOGGIES, archetypeTheme } from '../wrappedTheme'

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
        case 'superhero':
            return `${formatPercent(evidence)} of tool calls came back without an error, and fast.`
        case 'rocket':
            return `Calls grew ${evidence}× since your first full month.`
        case 'all_rounder':
            return 'No single pattern stood out. Agents used a bit of everything.'
    }
}

export function ArchetypeCard({ card }: { card: MCPWrappedArchetypeCardApi }): JSX.Element {
    const Hoggie = ARCHETYPE_HOGGIES[card.archetype]
    return (
        <WrappedCard
            cardKey="archetype"
            kicker="Your server's personality"
            theme={archetypeTheme(card.archetype)}
            hideHoggie
        >
            <h2 className="MCPWrapped__pop m-0 text-4xl font-bold leading-tight">{ARCHETYPE_NAMES[card.archetype]}</h2>
            <p className="MCPWrapped__rise m-0 text-base">
                <strong className="block">{ARCHETYPE_TAGLINES[card.archetype]}</strong>
                {describe(card)}
            </p>
            <div className="MCPWrapped__pop relative mt-auto flex justify-center">
                <span className="absolute bottom-6 size-56 rounded-full bg-white/20 blur-3xl" />
                <Hoggie className="MCPWrapped__hero-hoggie relative size-72" loading="eager" />
            </div>
        </WrappedCard>
    )
}
