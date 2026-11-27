import { RefObject, useEffect, useRef } from 'react'

import { AdventFlowNode } from './adventFlowLayout'

// The closing card stays mounted while it slides out, so focus on one of its links is lost when it unmounts.
function focusIsLost(root: HTMLElement): boolean {
    const focused = document.activeElement
    return (
        !focused ||
        focused === document.body ||
        !!root.querySelector('[data-attr="advent-door-card"]')?.contains(focused)
    )
}

// The card renders after the track, so without this a keyboard user tabs through every later door
// before reaching the answers, and on the phone the first offscreen door scrolls the card away.
export function useAdventCardFocus(
    stage: RefObject<HTMLElement>,
    isPinned: boolean,
    cardNode: AdventFlowNode | null
): void {
    const lastPinned = useRef<string | null>(null)
    const pinnedNodeId = isPinned ? (cardNode?.id ?? null) : null

    useEffect(() => {
        const root = stage.current
        if (!root) {
            return
        }
        if (pinnedNodeId) {
            lastPinned.current = pinnedNodeId
            root.querySelector<HTMLElement>('[data-attr="advent-door-card-close"]')?.focus({ preventScroll: true })
            return
        }
        const nodeId = lastPinned.current
        lastPinned.current = null
        if (nodeId && focusIsLost(root)) {
            root.querySelector<HTMLElement>(`button[aria-describedby="advent-flow-caption-${nodeId}"]`)?.focus({
                preventScroll: true,
            })
        }
    }, [stage, pinnedNodeId])
}
