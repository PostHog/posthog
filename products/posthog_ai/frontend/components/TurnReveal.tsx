import { type ReactNode, useSyncExternalStore } from 'react'

import type { TurnHoverStore } from '../utils/turnHoverStore'
import { TurnRevealContext } from './TurnRevealContext'

/** Wraps a turn trailer: tells its content when the turn is hovered, and counts the trailer as part of the turn. */
export function TurnReveal({
    store,
    turnId,
    children,
}: {
    store: TurnHoverStore
    turnId: string
    children: ReactNode
}): JSX.Element {
    const revealed = useSyncExternalStore(store.subscribe, () => store.getHoveredTurnId() === turnId)
    return (
        <TurnRevealContext.Provider value={revealed}>
            <div onMouseEnter={() => store.enter(turnId)} onMouseLeave={() => store.leave(turnId)}>
                {children}
            </div>
        </TurnRevealContext.Provider>
    )
}
