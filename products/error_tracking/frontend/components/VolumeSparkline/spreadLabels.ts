export type LabelSpreadItem = {
    /** Where the label wants to sit — the x of the thing it points at. */
    center: number
    halfWidth: number
}

/** Spread overlapping labels along one axis, preserving order and staying within `[min, max]`.
 *  When they can't all fit, the leftmost spill past `min` rather than stacking up. */
export function spreadLabels(items: LabelSpreadItem[], minGap: number, min: number, max: number): number[] {
    const centers = items.map((item) => item.center)
    const order = items.map((_, index) => index).sort((a, b) => items[a].center - items[b].center)

    for (let k = 0; k < order.length; k++) {
        const i = order[k]
        let center = Math.max(centers[i], min + items[i].halfWidth)
        if (k > 0) {
            const previous = order[k - 1]
            center = Math.max(center, centers[previous] + items[previous].halfWidth + minGap + items[i].halfWidth)
        }
        centers[i] = center
    }

    for (let k = order.length - 1; k >= 0; k--) {
        const i = order[k]
        let center = Math.min(centers[i], max - items[i].halfWidth)
        if (k < order.length - 1) {
            const next = order[k + 1]
            center = Math.min(center, centers[next] - items[next].halfWidth - minGap - items[i].halfWidth)
        }
        centers[i] = center
    }

    return centers
}
