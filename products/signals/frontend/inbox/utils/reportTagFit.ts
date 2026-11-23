/**
 * How many leading tags fit on one line of `available` pixels. The `+n` chip takes space only when
 * a tag is left over, so a last tag that fits in the place of the `+1` chip shows instead of it.
 * The count never drops below `minimum`, so the tags in the active filter always show, truncated if
 * they must be.
 */
export function fitReportTagCount({
    tagWidths,
    overflowWidth,
    available,
    gap,
    minimum = 0,
}: {
    tagWidths: number[]
    overflowWidth: number
    available: number
    gap: number
    minimum?: number
}): number {
    const total = tagWidths.reduce((sum, width, index) => sum + width + (index > 0 ? gap : 0), 0)
    if (total <= available) {
        return tagWidths.length
    }
    let used = 0
    for (let index = 0; index < tagWidths.length; index++) {
        used += tagWidths[index] + (index > 0 ? gap : 0)
        if (used + gap + overflowWidth > available) {
            return Math.max(index, minimum)
        }
    }
    return tagWidths.length
}
