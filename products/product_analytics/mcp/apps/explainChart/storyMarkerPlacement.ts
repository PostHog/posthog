export interface Point {
    x: number
    y: number
}

export interface Rect {
    left: number
    top: number
    right: number
    bottom: number
}

export interface MarkerObstacles {
    /** Each drawn line as its points in pixels, ordered by x. */
    lines: Point[][]
    bars: Rect[]
}

export interface MarkerLayout {
    radius: number
    /** From the marked point to the badge's centre. */
    distance: number
    bounds: Rect
}

// Straight up first, then fanning out to either side, so a clear sky keeps every badge above its point.
const ANGLES = [-90, -60, -120, -30, -150, 0, 180, 30, 150, 60, 120, 90].map((degrees) => (degrees * Math.PI) / 180)
const RINGS = [1, 1.6]
const CLEARANCE = 4
const TAIL_HALF_WIDTH = 2.5

function distanceToSegment(point: Point, from: Point, to: Point): number {
    const dx = to.x - from.x
    const dy = to.y - from.y
    const lengthSquared = dx * dx + dy * dy
    const t =
        lengthSquared === 0
            ? 0
            : Math.max(0, Math.min(1, ((point.x - from.x) * dx + (point.y - from.y) * dy) / lengthSquared))
    return Math.hypot(point.x - (from.x + t * dx), point.y - (from.y + t * dy))
}

function distanceToRect(point: Point, rect: Rect): number {
    const dx = Math.max(rect.left - point.x, 0, point.x - rect.right)
    const dy = Math.max(rect.top - point.y, 0, point.y - rect.bottom)
    return Math.hypot(dx, dy)
}

function firstIndexFrom(line: Point[], x: number): number {
    let low = 0
    let high = line.length
    while (low < high) {
        const middle = (low + high) >> 1
        if (line[middle]!.x < x) {
            low = middle + 1
        } else {
            high = middle
        }
    }
    return low
}

function distanceToLines(point: Point, lines: Point[][], reach: number): number {
    let nearest = Infinity
    for (const line of lines) {
        const end = firstIndexFrom(line, point.x + reach)
        for (let index = Math.max(firstIndexFrom(line, point.x - reach) - 1, 0); index < end; index++) {
            const next = line[index + 1]
            nearest = Math.min(
                nearest,
                next
                    ? distanceToSegment(point, line[index]!, next)
                    : Math.hypot(point.x - line[index]!.x, point.y - line[index]!.y)
            )
        }
    }
    return nearest
}

export function placeMarkers(anchors: Point[], obstacles: MarkerObstacles, layout: MarkerLayout): Point[] {
    const { radius, distance, bounds } = layout
    const placed: Point[] = []
    const reach = distance * RINGS[RINGS.length - 1]! + radius * 2

    const clearanceAt = (center: Point, anchor: Point): number => {
        if (
            center.x - radius < bounds.left ||
            center.x + radius > bounds.right ||
            center.y - radius < bounds.top ||
            center.y + radius > bounds.bottom
        ) {
            return -Infinity
        }
        // The tail starts on the line, so its midpoint only has to stay off the line, not keep the badge's margin.
        const length = Math.hypot(center.x - anchor.x, center.y - anchor.y)
        const along = (length - radius) / 2 / length
        const tailMiddle = { x: anchor.x + (center.x - anchor.x) * along, y: anchor.y + (center.y - anchor.y) * along }
        let clearance = Math.min(
            distanceToLines(center, obstacles.lines, reach) - radius,
            distanceToLines(tailMiddle, obstacles.lines, reach) - TAIL_HALF_WIDTH + CLEARANCE
        )
        for (const bar of obstacles.bars) {
            clearance = Math.min(clearance, distanceToRect(center, bar) - radius)
        }
        for (const other of placed) {
            clearance = Math.min(clearance, Math.hypot(center.x - other.x, center.y - other.y) - radius * 2)
        }
        for (const other of anchors) {
            if (other !== anchor) {
                clearance = Math.min(clearance, Math.hypot(center.x - other.x, center.y - other.y) - radius)
            }
        }
        return clearance
    }

    for (const anchor of anchors) {
        let best: { center: Point; clearance: number } | null = null
        search: for (const ring of RINGS) {
            for (const angle of ANGLES) {
                const center = {
                    x: anchor.x + Math.cos(angle) * distance * ring,
                    y: anchor.y + Math.sin(angle) * distance * ring,
                }
                const clearance = clearanceAt(center, anchor)
                if (clearance >= CLEARANCE) {
                    best = { center, clearance }
                    break search
                }
                if (!best || clearance > best.clearance) {
                    best = { center, clearance }
                }
            }
        }
        placed.push(best!.center)
    }
    return placed
}
