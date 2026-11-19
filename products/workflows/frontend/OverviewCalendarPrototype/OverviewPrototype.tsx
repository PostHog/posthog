// PROTOTYPE (throwaway, never merged). PostHog/michaelr-context#420, round 3: the overview of Email & Messaging,
// switchable via `?variant=`. B3 is performance with insights for a busy account; "B3, new account" is the same
// page with no sends, no conversion goal and no scanner, to show the empty states. Earlier rounds live in the
// branch history. Built as one self-contained page, so any navigation shape can mount it. All data is invented.
import { OverviewInsights } from './OverviewInsights'
import { PrototypeSwitcher, PrototypeVariant, usePrototypeVariant } from './PrototypeSwitcher'

export const OVERVIEW_VARIANTS: PrototypeVariant[] = [
    { key: 'B3', name: 'Performance with insights', flags: 'agent contract: workflow stats' },
    { key: 'B3-new', name: 'New account' },
]

export function OverviewPrototype(): JSX.Element {
    const variant = usePrototypeVariant(OVERVIEW_VARIANTS)
    return (
        <div data-quill className="@container pb-20">
            <OverviewInsights key={variant.key} newAccount={variant.key === 'B3-new'} />
            <PrototypeSwitcher variants={OVERVIEW_VARIANTS} page="Overview" />
        </div>
    )
}
