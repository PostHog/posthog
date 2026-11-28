import { useCallback, useRef } from 'react'

import { AdventCardState } from '../useAdventCard'

export interface AdventFlowHover {
    onEnter: (doorId: string) => void
    onLeave: () => void
}

// useAdventCard returns new handlers on every render. Handing those to the steps would re-render all of them
// on each hover, so the steps get handlers that keep their identity and call the latest card state.
export function useAdventFlowHover(card: AdventCardState): AdventFlowHover {
    const latest = useRef(card)
    latest.current = card
    const onEnter = useCallback((doorId: string): void => latest.current.onEnterDoor(doorId), [])
    const onLeave = useCallback((): void => latest.current.onLeaveDoor(), [])
    return { onEnter, onLeave }
}
