export interface TitleGeometry {
    /** Rise from the title's rest center to the chip row center. */
    travel: number
    /** How far right the title ends, past the chip. */
    shift: number
    endScale: number
    /** Space between the chip row's bottom and the title's box at rest. */
    gap: number
    /** Half the title's line height at full size. */
    halfHeight: number
}

export interface TitleTransform {
    translateX: number
    translateY: number
    scale: number
}

function clamp01(value: number): number {
    'worklet'
    return Math.min(Math.max(value, 0), 1)
}

/** Moves the large title from its rest position to the chip row as the user scrolls, scaled about its left center. */
export function collapsingTitleTransform(scrollY: number, geometry: TitleGeometry): TitleTransform {
    'worklet'
    const { travel, shift, endScale, gap, halfHeight } = geometry
    const progress = travel > 0 ? clamp01(scrollY / travel) : 0
    // The shift must finish before the title's box rises into the chip row, or the title draws over the chip.
    const rise = travel - halfHeight * (1 - endScale)
    const lead = rise > 0 ? clamp01(gap / rise) : 1
    const q = lead > 0 ? clamp01(progress / lead) : 1
    return {
        translateX: shift * q * q * (3 - 2 * q),
        translateY: -travel * progress,
        scale: 1 - (1 - endScale) * progress,
    }
}
