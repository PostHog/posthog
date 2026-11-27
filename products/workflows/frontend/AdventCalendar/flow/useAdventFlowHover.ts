import { MutableRefObject, useMemo, useRef } from 'react'

import { AdventCardState } from '../useAdventCard'

export interface AdventFlowHover {
    // The latest state of the card, which AdventFlowCard writes on each of its renders.
    card: MutableRefObject<AdventCardState | null>
    onEnter: (doorId: string) => void
    onLeave: () => void
    clearHover: () => void
}

// The card's hover state lives in AdventFlowCard, so a hover re-renders the card and not the stage with all of
// its steps. The stage and the steps reach that state through these handlers, which keep their identity.
export function useAdventFlowHover(): AdventFlowHover {
    const card = useRef<AdventCardState | null>(null)
    return useMemo(
        () => ({
            card,
            onEnter: (doorId: string): void => card.current?.onEnterDoor(doorId),
            onLeave: (): void => card.current?.onLeaveDoor(),
            clearHover: (): void => card.current?.clearHover(),
        }),
        []
    )
}
