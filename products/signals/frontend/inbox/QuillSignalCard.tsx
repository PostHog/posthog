import type { SignalNode } from 'scenes/debug/signals/types'

import { QuillGenericSignalCard } from './components/signalCards/QuillGenericSignalCard'
import { QUILL_SIGNAL_CARD_REGISTRY } from './components/signalCards/quillRegistry'
import { matchSignalCard } from './components/signalCards/signalCardMatchers'

/** Quill sibling of `SignalCard`: the same matching order and generic fallback, rendered with the quill cards. */
export function QuillSignalCard({ signal }: { signal: SignalNode }): JSX.Element {
    const key = matchSignalCard(signal)
    const Component = key ? QUILL_SIGNAL_CARD_REGISTRY[key] : QuillGenericSignalCard
    return <Component signal={signal} />
}
