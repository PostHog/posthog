// PROTOTYPE (throwaway, never merged). Round 1 of PostHog/michaelr-context#420: three overview pages for
// Email & Messaging, switchable via `?variant=` (A attention first, B performance, C timeline). Built as one
// self-contained page, so any navigation shape can mount it. All data is invented in prototypeData.ts.
import { OverviewAttention } from './OverviewAttention'
import { OverviewPerformance } from './OverviewPerformance'
import { OverviewTimeline } from './OverviewTimeline'
import { PrototypeSwitcher, PrototypeVariant, usePrototypeVariant } from './PrototypeSwitcher'

export const OVERVIEW_VARIANTS: PrototypeVariant[] = [
    { key: 'A', name: 'Attention first', flags: 'low use: workflow Logs tab' },
    { key: 'B', name: 'Performance', flags: 'agent contract: workflow stats' },
    { key: 'C', name: 'Timeline', flags: 'low use: calendar navigation' },
]

export function OverviewPrototype(): JSX.Element {
    const variant = usePrototypeVariant(OVERVIEW_VARIANTS)
    return (
        <div data-quill className="@container pb-20">
            {variant.key === 'A' ? <OverviewAttention /> : null}
            {variant.key === 'B' ? <OverviewPerformance /> : null}
            {variant.key === 'C' ? <OverviewTimeline /> : null}
            <PrototypeSwitcher variants={OVERVIEW_VARIANTS} page="Overview" />
        </div>
    )
}
