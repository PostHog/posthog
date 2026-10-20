import { type ReactNode, useEffect, useRef, useSyncExternalStore } from 'react'

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
    // Removing a hovered node fires no mouseleave, so a row the virtualizer recycles out would leave its turn
    // revealed. Only the wrapper the pointer is inside may clear it, or unmounting a row would hide the time
    // while the pointer rests on the same turn's trailer.
    const pointerInside = useRef(false)
    useEffect(
        () => () => {
            if (pointerInside.current) {
                store.leave()
            }
        },
        [store]
    )
    if (!turnId) {
        return <>{children}</>
    }
    return (
        <TurnRevealContext.Provider value={revealed}>
            <div
                onMouseEnter={() => {
                    pointerInside.current = true
                    store.enter(turnId)
                }}
                onMouseLeave={() => {
                    pointerInside.current = false
                    store.leave()
                }}
            >
                {children}
            </div>
        </TurnRevealContext.Provider>
    )
}
