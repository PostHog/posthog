/** Space kept between the stuck map block and a row scrolled into view. */
const ROW_MARGIN = 8

export interface RowScrollInput {
    /** The row's top and height in the scroll content. */
    rowTop: number
    rowHeight: number
    /** The block that sticks under the chrome: its top and height in the scroll content. */
    blockTop: number
    blockHeight: number
    /** Where the stuck block's top sits in the viewport. */
    stickTop: number
    scrollY: number
    viewportHeight: number
    contentHeight: number
}

/**
 * The scroll offset that shows a row just under the stuck block, or null when the row is on screen already. Rows
 * scroll under the block, so a row above the block's bottom edge counts as hidden.
 */
export function rowScrollTarget(input: RowScrollInput): number | null {
    const { rowTop, rowHeight, blockTop, blockHeight, stickTop, scrollY, viewportHeight, contentHeight } = input
    const visibleTop = Math.max(blockTop + blockHeight - scrollY, stickTop + blockHeight)
    const onScreen = rowTop - scrollY
    if (onScreen >= visibleTop && onScreen + rowHeight <= viewportHeight) {
        return null
    }
    const target = rowTop - stickTop - blockHeight - ROW_MARGIN
    return Math.max(0, Math.min(target, contentHeight - viewportHeight))
}
