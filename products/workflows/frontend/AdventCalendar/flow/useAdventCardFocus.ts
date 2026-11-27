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

const doorOfNode = (nodeId: string): string => `button[aria-describedby="advent-flow-caption-${nodeId}"]`

// The card renders after the track, so without this a keyboard user tabs through every later door
// before reaching the answers, and on the phone the first offscreen door scrolls the card away.
export function useAdventCardFocus(
    stage: RefObject<HTMLElement>,
    isPinned: boolean,
    cardNode: AdventFlowNode | null,
    onTabOut: () => void
): void {
    const lastPinned = useRef<string | null>(null)
    const pinnedNodeId = isPinned ? (cardNode?.id ?? null) : null
    // An answer swaps the focused option for the shares while the card stays pinned, so a change of the door's
    // status runs the effect again.
    const pinnedStatus = isPinned ? cardNode?.door?.status : undefined

    useEffect(() => {
        const root = stage.current
        if (!root) {
            return
        }
        if (pinnedNodeId) {
            if (lastPinned.current !== pinnedNodeId || document.activeElement === document.body) {
                root.querySelector<HTMLElement>('[data-attr="advent-door-card-close"]')?.focus({ preventScroll: true })
            }
            lastPinned.current = pinnedNodeId
            return
        }
        const nodeId = lastPinned.current
        lastPinned.current = null
        if (nodeId && focusIsLost(root)) {
            root.querySelector<HTMLElement>(doorOfNode(nodeId))?.focus({
                preventScroll: true,
            })
        }
    }, [stage, pinnedNodeId, pinnedStatus])

    // Focus moved into the card, which sits after every door, so Tab from its last control goes on to the door
    // after the pinned one, and Shift+Tab from its first control back to the pinned door. Both close the card.
    useEffect(() => {
        const root = stage.current
        if (!root || !pinnedNodeId) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            const controls = root.querySelectorAll('[data-attr="advent-door-card"] :is(button, a[href])')
            const edge = event.shiftKey ? controls[0] : controls[controls.length - 1]
            if (event.key !== 'Tab' || document.activeElement !== edge) {
                return
            }
            const doors = Array.from(
                root.querySelectorAll<HTMLElement>('button[aria-describedby^="advent-flow-caption-"]')
            )
            const pinned = doors.findIndex((door) => door.matches(doorOfNode(pinnedNodeId)))
            const next = pinned >= 0 ? doors[pinned + (event.shiftKey ? 0 : 1)] : undefined
            onTabOut()
            if (next) {
                event.preventDefault()
                next.focus()
            }
        }
        root.addEventListener('keydown', onKeyDown)
        return () => root.removeEventListener('keydown', onKeyDown)
    }, [stage, pinnedNodeId, onTabOut])
}
