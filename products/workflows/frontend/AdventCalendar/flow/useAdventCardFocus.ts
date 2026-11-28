import { RefObject, useEffect, useRef } from 'react'

import { AdventFlowNode } from './adventFlowLayout'

const CARD = '[data-attr="advent-door-card"]'

// The closing card stays mounted while it slides out, so focus on one of its links is lost when it unmounts.
function focusIsLost(root: HTMLElement): boolean {
    const focused = document.activeElement
    return !focused || focused === document.body || !!root.querySelector(CARD)?.contains(focused)
}

const doorOfNode = (nodeId: string): string => `button[aria-describedby="advent-flow-caption-${nodeId}"]`

const isScrollStop = (body: HTMLElement | null | undefined): body is HTMLElement =>
    !!body && body.scrollHeight > body.clientHeight && !body.querySelector('button, a[href]')

function lastStopOf(card: Element | null): HTMLElement | null {
    const stops = Array.from(card?.querySelectorAll<HTMLElement>('button, a[href]') ?? []).filter(
        (stop) => stop.tabIndex >= 0
    )
    const body = card?.querySelector<HTMLElement>('.AdventCard__body')
    return isScrollStop(body) ? body : (stops[stops.length - 1] ?? null)
}

function markScrollStop(card: Element | null): void {
    const body = card?.querySelector<HTMLElement>('.AdventCard__body')
    if (isScrollStop(body)) {
        body.tabIndex = 0
    } else {
        body?.removeAttribute('tabindex')
    }
}

export interface AdventCardGuards {
    onFocusStart: () => void
    onFocusEnd: () => void
}

export function useAdventCardFocus(
    stage: RefObject<HTMLElement>,
    isPinned: boolean,
    cardNode: AdventFlowNode | null,
    onPin: (doorId: string) => void
): AdventCardGuards {
    const lastPinned = useRef<string | null>(null)
    const lastShown = useRef<string | null>(null)
    const isKeyboard = useRef(false)
    const shownNodeId = cardNode?.id ?? null
    const pinnedNodeId = isPinned ? (cardNode?.id ?? null) : null
    // An answer swaps the focused option for the shares while the card stays pinned, so a change of the door's
    // status runs the effect again.
    const pinnedStatus = isPinned ? cardNode?.door?.status : undefined
    const hoveredDoorId = isPinned ? null : (cardNode?.door?.id ?? null)

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
            lastShown.current = shownNodeId
            return
        }
        const nodeId = lastPinned.current ?? (lastShown.current !== shownNodeId ? lastShown.current : null)
        lastPinned.current = null
        lastShown.current = shownNodeId
        if (nodeId && focusIsLost(root)) {
            root.querySelector<HTMLElement>(doorOfNode(nodeId))?.focus({
                preventScroll: true,
            })
        }
    }, [stage, pinnedNodeId, shownNodeId, pinnedStatus])

    useEffect(() => {
        const root = stage.current
        if (!root) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            isKeyboard.current = event.key === 'Tab'
            if (isKeyboard.current && !hoveredDoorId) {
                markScrollStop(root.querySelector(CARD))
            }
        }
        const onPointerDown = (): void => {
            isKeyboard.current = false
        }
        const onFocusIn = (event: FocusEvent): void => {
            if (hoveredDoorId && isKeyboard.current && (event.target as Element).closest(CARD)) {
                onPin(hoveredDoorId)
            }
        }
        window.addEventListener('keydown', onKeyDown, true)
        window.addEventListener('pointerdown', onPointerDown, true)
        root.addEventListener('focusin', onFocusIn)
        return () => {
            window.removeEventListener('keydown', onKeyDown, true)
            window.removeEventListener('pointerdown', onPointerDown, true)
            root.removeEventListener('focusin', onFocusIn)
        }
    }, [stage, hoveredDoorId, onPin])

    const close = (): HTMLElement | null | undefined =>
        stage.current?.querySelector<HTMLElement>(`${CARD} [data-attr="advent-door-card-close"]`)
    return {
        onFocusStart: () => {
            const last = lastStopOf(stage.current?.querySelector(CARD) ?? null)
            last?.focus()
            if (document.activeElement !== last) {
                close()?.focus()
            }
        },
        onFocusEnd: () => close()?.focus(),
    }
}
