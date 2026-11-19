// PROTOTYPE (throwaway, never merged). PostHog/michaelr-context#420, round 2: the overview of Email & Messaging,
// switchable via `?variant=`. B2 is performance with insights; B is round 1's performance page, for comparison.
// Round 1's A (attention first) and C (timeline) live in the branch history. Built as one self-contained page, so
// any navigation shape can mount it. All data is invented.
import { OverviewInsights } from './OverviewInsights'
import { OverviewPerformance } from './OverviewPerformance'
import { PrototypeSwitcher, PrototypeVariant, usePrototypeVariant } from './PrototypeSwitcher'

export const OVERVIEW_VARIANTS: PrototypeVariant[] = [
    { key: 'B2', name: 'Performance with insights', flags: 'agent contract: workflow stats' },
    { key: 'B', name: 'Performance, round 1', flags: 'agent contract: workflow stats' },
]

export function OverviewPrototype(): JSX.Element {
    const variant = usePrototypeVariant(OVERVIEW_VARIANTS)
    return (
        <div data-quill className="@container pb-20">
            {variant.key === 'B2' ? <OverviewInsights /> : null}
            {variant.key === 'B' ? <OverviewPerformance /> : null}
            <PrototypeSwitcher variants={OVERVIEW_VARIANTS} page="Overview" />
        </div>
    )
}
