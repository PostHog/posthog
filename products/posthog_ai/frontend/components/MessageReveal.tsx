import { type ReactNode, useState } from 'react'

import { TurnRevealContext } from './TurnRevealContext'

/**
 * Reveals a message's footer while the pointer is over that message. For a thread that does not group rows
 * into turns; `ThreadView` reveals a whole turn through `TurnReveal` instead.
 */
export function MessageReveal({ children }: { children: ReactNode }): JSX.Element {
    const [hovered, setHovered] = useState(false)
    return (
        <TurnRevealContext.Provider value={hovered}>
            <div onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}>
                {children}
            </div>
        </TurnRevealContext.Provider>
    )
}
