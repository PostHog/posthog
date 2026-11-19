// PROTOTYPE (throwaway, never merged). Round 1 of PostHog/michaelr-context#420: three overview pages for
// Email & Messaging, switchable via `?variant=` (A attention first, B performance, C timeline). Built as one
// self-contained page, so any navigation shape can mount it. All data is invented in prototypeData.ts.
import { OverviewAttention } from './OverviewAttention'
import { OverviewPerformance } from './OverviewPerformance'
import { OverviewTimeline } from './OverviewTimeline'
import { PrototypeSwitcher, PrototypeVariant, usePrototypeVariant } from './PrototypeSwitcher'

export const OVERVIEW_VARIANTS: PrototypeVariant[] = [
    { key: 'A', name: 'Attention first' },
    { key: 'B', name: 'Performance' },
    { key: 'C', name: 'Timeline' },
]

export function OverviewPrototype(): JSX.Element {
    const variant = usePrototypeVariant(OVERVIEW_VARIANTS)
    return (
        <div className="@container pb-20">
            {variant.key === 'A' ? <OverviewAttention /> : null}
            {variant.key === 'B' ? <OverviewPerformance /> : null}
            {variant.key === 'C' ? <OverviewTimeline /> : null}
            <PrototypeSwitcher variants={OVERVIEW_VARIANTS} page="Overview" />
        </div>
    )
}
