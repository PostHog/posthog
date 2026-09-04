import { DEFAULT_Y_AXIS_ID } from '@posthog/quill-charts'

/** Peak ratio at which a series leaves the group below it. A full order of magnitude is too
 *  coarse: a 3x spread already flattens the smaller series, and that spread is the usual
 *  reason to ask for a second axis. */
const MIN_SPLIT_RATIO = 3
const MAX_Y_AXES = 4

/** Assign a y-axis id per series so series of similar magnitude share an axis. Series are
 *  clustered on their max |value|: a group holds every series within MIN_SPLIT_RATIO of its
 *  smallest peak, so a chain of small steps cannot stretch one group over a wide range. The
 *  count is capped at MAX_Y_AXES, keeping the splits with the largest ratio. The first series'
 *  group keeps the default axis id; other groups get stable ids in series order. */
export function computeMagnitudeAxisIds(datasets: readonly (readonly number[])[]): string[] {
    const peaks = datasets.map((data) => {
        let max = 0
        for (const value of data) {
            const abs = Math.abs(value)
            if (Number.isFinite(abs) && abs > max) {
                max = abs
            }
        }
        return max > 0 ? max : null
    })

    const measured = peaks
        .flatMap((peak, seriesIndex) => (peak === null ? [] : [{ peak, seriesIndex }]))
        .sort((a, b) => a.peak - b.peak)

    const splits: { pos: number; ratio: number }[] = []
    let groupMin: number | null = null
    let previousPeak = 0
    measured.forEach(({ peak }, pos) => {
        if (groupMin === null) {
            groupMin = peak
        } else if (peak / groupMin >= MIN_SPLIT_RATIO) {
            splits.push({ pos, ratio: peak / previousPeak })
            groupMin = peak
        }
        previousPeak = peak
    })

    const splitPositions = new Set(
        splits
            .sort((a, b) => b.ratio - a.ratio)
            .slice(0, MAX_Y_AXES - 1)
            .map(({ pos }) => pos)
    )

    // Flat (all-zero or empty) series carry no magnitude and join the lowest group.
    const groupOf = datasets.map(() => 0)
    let group = 0
    measured.forEach(({ seriesIndex }, k) => {
        if (splitPositions.has(k)) {
            group += 1
        }
        groupOf[seriesIndex] = group
    })

    const firstGroup = groupOf[0]
    const idOf = new Map<number, string>(firstGroup === undefined ? [] : [[firstGroup, DEFAULT_Y_AXIS_ID]])
    return groupOf.map((g) => {
        let id = idOf.get(g)
        if (!id) {
            id = `y${idOf.size}`
            idOf.set(g, id)
        }
        return id
    })
}
