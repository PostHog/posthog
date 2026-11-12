import type { RowAnchor } from '@/features/inbox/contextMenuPlacement'

export interface PinFrame extends RowAnchor {
    id: string
}

/** Insert at the target's position; preserve the relative order of every other pin. */
export function dropPin(ids: readonly string[], source: string, target: string): string[] {
    const from = ids.indexOf(source)
    const to = ids.indexOf(target)
    if (from < 0 || to < 0 || from === to) return [...ids]
    const next = ids.filter((id) => id !== source)
    next.splice(to, 0, source)
    return next
}

/** Rectangle distance handles mixed-height cards and the two-column layout without assuming row sizes. */
export function nearestPin(frames: readonly PinFrame[], x: number, y: number): PinFrame | null {
    let closest: PinFrame | null = null
    let distance = Number.POSITIVE_INFINITY
    for (const frame of frames) {
        const dx = Math.max(frame.x - x, 0, x - frame.x - frame.width)
        const dy = Math.max(frame.y - y, 0, y - frame.y - frame.height)
        const next = dx * dx + dy * dy
        if (next < distance) {
            closest = frame
            distance = next
        }
    }
    return closest
}

export function dragScrollStep(y: number, top: number, bottom: number): number {
    const edge = 64
    if (y < top + edge) return -8 * Math.min(1, Math.max(0, (top + edge - y) / edge))
    if (y > bottom - edge) return 8 * Math.min(1, Math.max(0, (y - bottom + edge) / edge))
    return 0
}
