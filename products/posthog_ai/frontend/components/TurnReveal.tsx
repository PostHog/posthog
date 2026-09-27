import { type ReactNode, useSyncExternalStore } from 'react'

import type { TurnHoverStore } from '../utils/turnHoverStore'
import { TurnRevealContext } from './TurnRevealContext'

/** Hovering the trailer itself counts as hovering the turn, so the time does not vanish as the pointer reaches it. */
export function TurnReveal({
    store,
    turnId,
    children,
}: {
    store: TurnHoverStore
    turnId: string | undefined
    children: ReactNode
}): JSX.Element {
    const revealed = useSyncExternalStore(store.subscribe, () => !!turnId && store.getHoveredTurnId() === turnId)
    if (!turnId) {
        return <>{children}</>
    }
    return (
        <TurnRevealContext.Provider value={revealed}>
            <div onMouseEnter={() => store.enter(turnId)} onMouseLeave={() => store.leave()}>
                {children}
            </div>
        </TurnRevealContext.Provider>
    )
}
