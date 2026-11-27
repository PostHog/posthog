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
const doorOfNode = (nodeId: string): string => `button[aria-describedby="advent-flow-caption-${nodeId}"]`

export function useAdventCardFocus(
    stage: RefObject<HTMLElement>,
    isPinned: boolean,
    cardNode: AdventFlowNode | null,
    onTabOut: () => void
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
            root.querySelector<HTMLElement>(doorOfNode(nodeId))?.focus({
                preventScroll: true,
            })
        }
    }, [stage, pinnedNodeId])

    // Focus moved into the card, which sits after every door, so Tab from its last control goes on to the door
    // after the pinned one and closes the card, instead of leaving the stage.
    useEffect(() => {
        const root = stage.current
        if (!root || !pinnedNodeId) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            const controls = root.querySelectorAll('[data-attr="advent-door-card"] :is(button, a[href])')
            if (event.key !== 'Tab' || event.shiftKey || document.activeElement !== controls[controls.length - 1]) {
                return
            }
            const doors = Array.from(
                root.querySelectorAll<HTMLElement>('button[aria-describedby^="advent-flow-caption-"]')
            )
            const pinned = doors.findIndex((door) => door.matches(doorOfNode(pinnedNodeId)))
            const next = pinned >= 0 ? doors[pinned + 1] : undefined
            if (next) {
                event.preventDefault()
                onTabOut()
                next.focus()
            }
        }
        root.addEventListener('keydown', onKeyDown)
        return () => root.removeEventListener('keydown', onKeyDown)
    }, [stage, pinnedNodeId, onTabOut])
}
