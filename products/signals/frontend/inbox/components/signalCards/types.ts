import type { SignalNode } from 'scenes/debug/signals/types'

import type { SignalCardKey } from './signalCardMatchers'

/** Props every per-source signal card receives. The card narrows `signal.extra` itself via its type guard. */
export interface SignalCardProps {
    signal: SignalNode
}

export type SignalCardComponent = (props: SignalCardProps) => JSX.Element

/** One card per matcher key in `SIGNAL_CARD_MATCHERS`; each registry (Lemon, quill) fills its own. */
export type SignalCardRegistry = Record<SignalCardKey, SignalCardComponent>
