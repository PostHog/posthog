import type { SignalNode } from 'scenes/debug/signals/types'

/** Props every per-source signal card receives. The card narrows `signal.extra` itself via its type guard. */
export interface SignalCardProps {
    signal: SignalNode
}

/**
 * One entry in the signal-card registry. `matches` is evaluated in registry order, so more specific
 * entries must come before more general ones. The first matching entry renders the signal; if none
 * match, the generic fallback card is used.
 */
export interface SignalCardEntry {
    /** Stable identifier for the source/variant this entry renders. */
    key: string
    /** True when this entry should render `signal`. Registry order is priority. */
    matches: (signal: SignalNode) => boolean
    Component: (props: SignalCardProps) => JSX.Element
}
