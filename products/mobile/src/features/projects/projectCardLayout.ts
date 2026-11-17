export interface ProjectCardLayout {
    /** The title shares a row with the search field, and rows are 44pt instead of 56pt. */
    compact: boolean
    /** Add account stays below the list. Otherwise it is the last row of the list. */
    footerPinned: boolean
}

type Density = 'regular' | 'compact'

// The heights that the ProjectSheet styles give each part. Change both together.
const ROW: Record<Density, number> = { regular: 56, compact: 44 }
// Card padding, the title and search rows, and the gap above the list.
const CONTROLS: Record<Density, number> = { regular: 20 + 44 + 16 + 48 + 8 + 24, compact: 4 + 44 + 2 + 4 }
// The hairline above Add account and the gap below it.
const FOOTER_RULE = 3
const VISIBLE_ROWS = 2

function heightWithFooter(density: Density): number {
    return CONTROLS[density] + FOOTER_RULE + ROW[density] + VISIBLE_ROWS * ROW[density]
}

/** The shortest card that keeps two rows of projects above the Add account footer in the regular layout. */
export const MIN_HEIGHT_WITH_FOOTER = heightWithFooter('regular')

/**
 * Keeps two rows of projects in view above the Add account footer. A card too short for that, such as on a small phone
 * with the keyboard up, uses the compact layout. A card too short even then, such as on a phone in landscape with the
 * keyboard up, puts Add account at the end of the list, so the projects keep the room.
 */
export function projectCardLayout(cardHeight: number, windowHeight: number, addAccount: boolean): ProjectCardLayout {
    const shortWindow = windowHeight < 480
    if (!addAccount) {
        return { compact: shortWindow, footerPinned: false }
    }
    const compact = shortWindow || cardHeight < heightWithFooter('regular')
    return { compact, footerPinned: cardHeight >= heightWithFooter(compact ? 'compact' : 'regular') }
}
