/** Continuous time → x, so an event can sit between two bucket starts rather than snapping to one.
 *  A bucket's timestamp is its left edge, not its center. `null` when the step can't be derived. */
export function buildTimePositioner(
    dates: Date[],
    labels: string[],
    scaleX: (label: string) => number | undefined
): ((time: number) => number) | null {
    if (dates.length < 2 || labels.length < 2) {
        return null
    }
    const firstCenter = scaleX(labels[0])
    const secondCenter = scaleX(labels[1])
    if (firstCenter == null || secondCenter == null || !isFinite(firstCenter) || !isFinite(secondCenter)) {
        return null
    }
    const step = secondCenter - firstCenter
    const bucketMs = dates[1].getTime() - dates[0].getTime()
    if (step === 0 || bucketMs === 0) {
        return null
    }
    const originX = firstCenter - step / 2
    const originTime = dates[0].getTime()
    return (time: number) => originX + ((time - originTime) / bucketMs) * step
}
