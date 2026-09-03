import { DEFAULT_Y_AXIS_ID } from '@posthog/quill-charts'

const MAGNITUDE_GAP = 1
const MAX_Y_AXES = 4

/** Assign a y-axis id per series so series of similar magnitude share an axis. Series are
 *  clustered on log10 of their max |value|, splitting at the largest gaps of at least
 *  MAGNITUDE_GAP orders, capped at MAX_Y_AXES axes. The first series' group keeps the
 *  default axis id; other groups get stable ids in series order. */
export function computeMagnitudeAxisIds(datasets: readonly (readonly number[])[]): string[] {
    const magnitudes = datasets.map((data) => {
        let max = 0
        for (const value of data) {
            const abs = Math.abs(value)
            if (Number.isFinite(abs) && abs > max) {
                max = abs
            }
        }
        return max > 0 ? Math.log10(max) : null
    })

    const measured = magnitudes
        .flatMap((magnitude, seriesIndex) => (magnitude === null ? [] : [{ magnitude, seriesIndex }]))
        .sort((a, b) => a.magnitude - b.magnitude)

    const splitPositions = new Set(
        measured
            .flatMap((entry, k) => {
                const previous = measured[k - 1]
                return previous ? [{ pos: k, gap: entry.magnitude - previous.magnitude }] : []
            })
            .filter(({ gap }) => gap >= MAGNITUDE_GAP)
            .sort((a, b) => b.gap - a.gap)
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
