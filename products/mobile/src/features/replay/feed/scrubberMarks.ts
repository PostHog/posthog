import type { TickKind } from './feedStyle'

export interface ScrubberTick {
    key: string
    seconds: number
    kind: TickKind
    label: string
}

/** The closest two marks may sit on the bar, in points. */
export const MARK_GAP = 6

const PRIORITY: Record<TickKind, number> = { error: 3, rage: 2, key: 1, custom: 0 }

/**
 * Keeps the marks inside [start, end] and draws at most one per `MARK_GAP` points of bar, so a recording with
 * hundreds of events draws a bounded number of views. Within a slot the strongest kind wins (error, rage, key,
 * custom), and the earliest of those, so a mark still sits at a real event.
 */
export function clusterTicks(
    ticks: readonly ScrubberTick[],
    start: number,
    end: number,
    barWidth: number
): ScrubberTick[] {
    const span = end - start
    if (span <= 0 || barWidth <= 0) {
        return []
    }
    const slots = Math.max(1, Math.floor(barWidth / MARK_GAP))
    const best = new Map<number, ScrubberTick>()
    for (const tick of ticks) {
        if (tick.seconds < start || tick.seconds > end) {
            continue
        }
        const slot = Math.min(slots - 1, Math.floor(((tick.seconds - start) / span) * slots))
        const held = best.get(slot)
        if (
            !held ||
            PRIORITY[tick.kind] > PRIORITY[held.kind] ||
            (PRIORITY[tick.kind] === PRIORITY[held.kind] && tick.seconds < held.seconds)
        ) {
            best.set(slot, tick)
        }
    }
    return [...best.values()].sort((a, b) => a.seconds - b.seconds)
}
