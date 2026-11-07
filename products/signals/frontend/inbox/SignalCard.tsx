import type { SignalNode } from 'scenes/debug/signals/types'

import { GenericSignalCard } from './components/signalCards/GenericSignalCard'
import { SIGNAL_CARD_REGISTRY } from './components/signalCards/registry'
import { matchSignalCard } from './components/signalCards/signalCardMatchers'

/**
 * Renders a single signal as evidence in a report/PR detail view. Dispatches to a per-source card
 * via `SIGNAL_CARD_MATCHERS` (first matching entry wins), falling back to `GenericSignalCard` for
 * sources without a dedicated renderer.
 */
export function SignalCard({ signal }: { signal: SignalNode }): JSX.Element {
    const key = matchSignalCard(signal)
    const Component = key ? SIGNAL_CARD_REGISTRY[key] : GenericSignalCard
    return <Component signal={signal} />
}
