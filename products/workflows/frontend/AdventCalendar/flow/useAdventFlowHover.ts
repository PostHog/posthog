import { MutableRefObject, useMemo, useRef } from 'react'

import { AdventCardState } from '../useAdventCard'

export interface AdventFlowHover {
    card: MutableRefObject<AdventCardState | null>
    onEnter: (doorId: string) => void
    onLeave: () => void
    clearHover: () => void
}

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
