/** Builds a continuous time → x mapper so an event at an arbitrary timestamp can be placed between
 *  two bucket starts, not just snapped to one. Bars are band-scaled, so the step comes from two
 *  adjacent band centers and x is measured from the first bucket's left edge — the convention is
 *  that a bucket's timestamp sits at its left edge, not its center. Returns `null` when there's too
 *  little data to derive a step, or the scale hasn't resolved yet. */
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
