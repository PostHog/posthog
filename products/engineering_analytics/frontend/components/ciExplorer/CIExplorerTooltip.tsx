import { useValues } from 'kea'
import { type RefObject, useEffect, useRef, useState } from 'react'

import { CIExplorerTip, nodeTip } from '../../lib/ciExplorerDetails'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'

// The tooltip waits for the pointer to settle on a node. Moving to a neighbor then shows the next one at once.
const DELAY_MS = 600
const WARM_MS = 400
// A node drawn smaller than this cannot be read, so it is not what the pointer is on.
const MIN_NODE_HEIGHT = 20
const POINTER_GAP = 16
const EDGE_MARGIN = 8

interface ShownTip {
    tip: CIExplorerTip
    x: number
    y: number
}

/** A tooltip for whichever node the pointer rests on. One listener serves every node on the canvas. */
export function CIExplorerTooltip({ stage }: { stage: RefObject<HTMLElement> }): JSX.Element | null {
    const { workflows } = useValues(ciExplorerLogic)
    const [shown, setShown] = useState<ShownTip | null>(null)
    const box = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const element = stage.current
        if (!element) {
            return
        }
        let target: HTMLElement | null = null
        let timer: ReturnType<typeof setTimeout> | undefined
        let visible = false
        let hiddenAt = 0

        const hide = (): void => {
            clearTimeout(timer)
            if (visible) {
                hiddenAt = performance.now()
            }
            visible = false
            target = null
            setShown(null)
        }
        const onMove = (event: MouseEvent): void => {
            const node = (event.target as HTMLElement).closest<HTMLElement>('[data-node-id]')
            // A tile that is zoomed into shows its jobs, and those have their own tooltips.
            const zoomedIntoTile = node?.matches('.CIExplorer__card') && element.dataset.deep === 'true'
            const tip = node?.dataset.nodeId ? nodeTip(workflows, node.dataset.nodeId) : null
            if (
                !node ||
                !tip ||
                zoomedIntoTile ||
                event.buttons ||
                node.getBoundingClientRect().height < MIN_NODE_HEIGHT
            ) {
                hide()
                return
            }
            if (node === target) {
                return
            }
            const warm = visible || performance.now() - hiddenAt < WARM_MS
            hide()
            target = node
            const show = (): void => {
                visible = true
                setShown({ tip, x: event.clientX, y: event.clientY })
            }
            if (warm) {
                show()
            } else {
                timer = setTimeout(show, DELAY_MS)
            }
        }
        // A node reached with the keyboard shows its tooltip at once, beside the node.
        const onFocus = (event: FocusEvent): void => {
            const focused = event.target as HTMLElement
            const node = focused.closest<HTMLElement>('[data-node-id]')
            const tip = node?.dataset.nodeId ? nodeTip(workflows, node.dataset.nodeId) : null
            if (!node || !tip || !focused.matches(':focus-visible')) {
                return
            }
            hide()
            target = node
            visible = true
            const box = node.getBoundingClientRect()
            setShown({ tip, x: Math.min(box.right, window.innerWidth - 2 * POINTER_GAP), y: Math.max(0, box.top) })
        }
        element.addEventListener('mousemove', onMove)
        element.addEventListener('mouseleave', hide)
        element.addEventListener('focusin', onFocus)
        element.addEventListener('focusout', hide)
        for (const type of ['pointerdown', 'wheel', 'keydown']) {
            element.addEventListener(type, hide, { capture: true, passive: true })
        }
        return () => {
            clearTimeout(timer)
            element.removeEventListener('mousemove', onMove)
            element.removeEventListener('mouseleave', hide)
            element.removeEventListener('focusin', onFocus)
            element.removeEventListener('focusout', hide)
            for (const type of ['pointerdown', 'wheel', 'keydown']) {
                element.removeEventListener(type, hide, { capture: true })
            }
        }
    }, [stage, workflows])

    // The box is placed after it renders, when its size is known, so it never leaves the window.
    useEffect(() => {
        if (!shown || !box.current) {
            return
        }
        const { offsetWidth: width, offsetHeight: height } = box.current
        const below = shown.y + POINTER_GAP + height <= window.innerHeight
        box.current.style.left = `${Math.max(EDGE_MARGIN, Math.min(shown.x + POINTER_GAP, window.innerWidth - width - EDGE_MARGIN))}px`
        box.current.style.top = `${below ? shown.y + POINTER_GAP : Math.max(EDGE_MARGIN, shown.y - height - POINTER_GAP)}px`
        box.current.style.visibility = 'visible'
    }, [shown])

    if (!shown) {
        return null
    }
    return (
        <div
            ref={box}
            role="tooltip"
            className="pointer-events-none fixed z-[var(--z-tooltip)] max-w-80 rounded-md bg-[var(--color-text-primary)] px-3 py-2 text-xs text-[var(--color-bg-primary)]"
            // Hidden until the effect above has placed it. A utility class cannot do this, because utilities are `!important`.
            // eslint-disable-next-line react/forbid-dom-props
            style={{ visibility: 'hidden' }}
        >
            <b className="mb-1 block break-words font-semibold">{shown.tip.name}</b>
            <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5">
                {shown.tip.rows.map(([label, value]) => (
                    <div key={label} className="contents">
                        <dt className="opacity-65">{label}</dt>
                        <dd className="m-0 break-words font-mono">{value}</dd>
                    </div>
                ))}
            </dl>
        </div>
    )
}
