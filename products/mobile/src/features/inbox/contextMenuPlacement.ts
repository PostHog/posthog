import type { DisplayRect } from '@/ui/displayRegions'
/** A row's frame in window coordinates, from `measureInWindow`. */
export interface RowAnchor {
    x: number
    y: number
    width: number
    height: number
}

export interface ContextMenuPlacementInput {
    /** Row top edge in window coordinates. */
    rowTop: number
    /** Row bottom edge in window coordinates. */
    rowBottom: number
    menuHeight: number
    /** The menu never goes above this line, the bottom of the floating inbox header. */
    topLimit: number
    /** The menu never goes below this line, the top of the floating bottom bar. */
    bottomLimit: number
    gap?: number
}

export type ContextMenuSide = 'below' | 'above'

export interface ContextMenuPlacement {
    top: number
    side: ContextMenuSide
}

export const CONTEXT_MENU_GAP = 8

export function placeAnchoredMenu({
    anchor,
    frame,
    pane,
    width,
    height,
    gutter = 14,
}: {
    anchor: RowAnchor
    frame: DisplayRect
    pane: DisplayRect
    width: number
    height: number
    gutter?: number
}): { left: number; top: number; width: number; maxHeight: number; side: ContextMenuSide } {
    const fittedWidth = Math.min(width, Math.max(0, pane.width - gutter * 2))
    const maxHeight = Math.max(0, pane.height - gutter * 2)
    const placement = placeContextMenu({
        rowTop: anchor.y - frame.y,
        rowBottom: anchor.y - frame.y + anchor.height,
        menuHeight: Math.min(height, maxHeight),
        topLimit: pane.y + gutter,
        bottomLimit: pane.y + pane.height - gutter,
    })
    return {
        ...placement,
        left: Math.max(pane.x + gutter, Math.min(anchor.x - frame.x, pane.x + pane.width - gutter - fittedWidth)),
        width: fittedWidth,
        maxHeight,
    }
}

export function placeContextMenu({
    rowTop,
    rowBottom,
    menuHeight,
    topLimit,
    bottomLimit,
    gap = CONTEXT_MENU_GAP,
}: ContextMenuPlacementInput): ContextMenuPlacement {
    const below = rowBottom + gap
    if (below + menuHeight <= bottomLimit) {
        return { top: below, side: 'below' }
    }
    const above = rowTop - gap - menuHeight
    if (above >= topLimit) {
        return { top: above, side: 'above' }
    }
    // Neither side has room, so take the roomier side and pull the menu back inside the limits.
    const side: ContextMenuSide = bottomLimit - rowBottom >= rowTop - topLimit ? 'below' : 'above'
    const maxTop = Math.max(topLimit, bottomLimit - menuHeight)
    const preferred = side === 'below' ? below : above
    return { top: Math.min(Math.max(preferred, topLimit), maxTop), side }
}
