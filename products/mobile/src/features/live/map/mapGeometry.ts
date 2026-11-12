/** The world without the empty Pacific margins of the 2754 × 1200 source viewBox, in map units. */
export const WORLD_CROP = { x: 90, y: 16, width: 2580, height: 1156 } as const

export const WORLD_ASPECT_RATIO = WORLD_CROP.width / WORLD_CROP.height

export interface MapFit {
    /** Points per map unit. */
    scale: number
}

/** Fits the cropped world to `width` points, keeping its aspect ratio. */
export function fitMap(width: number): MapFit {
    return { scale: width / WORLD_CROP.width }
}

export type MapTransform = [{ translateX: number }, { translateY: number }, { scale: number }]

/**
 * Map units to points in the map's box, for the Skia `Group`. Skia multiplies the list left to right, so a point is
 * scaled first and translated second. `toMapPoint` is its inverse.
 */
export function mapTransform(fit: MapFit): MapTransform {
    return [{ translateX: -WORLD_CROP.x * fit.scale }, { translateY: -WORLD_CROP.y * fit.scale }, { scale: fit.scale }]
}

export interface MapPoint {
    x: number
    y: number
}

/** A point in the map's box, in points from its top left, as a point in map units. */
export function toMapPoint(fit: MapFit, x: number, y: number): MapPoint {
    return { x: x / fit.scale + WORLD_CROP.x, y: y / fit.scale + WORLD_CROP.y }
}

export interface HitPath {
    contains: (x: number, y: number) => boolean
    getBounds: () => { width: number; height: number }
}

const RING_STEPS = 8

/** Eight points at half the slop and eight at the full slop around the tap, nearest first. */
function rings(point: MapPoint, slop: number): MapPoint[] {
    const around = (radius: number): MapPoint[] =>
        Array.from({ length: RING_STEPS }, (_, step) => {
            const angle = (step / RING_STEPS) * 2 * Math.PI
            return { x: point.x + radius * Math.cos(angle), y: point.y + radius * Math.sin(angle) }
        })
    return slop > 0 ? [...around(slop / 2), ...around(slop)] : []
}

/**
 * The country with visitors under a tap, or null. A tap inside a country without visitors returns null, so it never
 * selects a neighbor. Small countries are a few points wide on a phone, so a tap on the sea, or inside a country
 * smaller than `slop` map units, also tries points up to `slop` away.
 */
export function pickCountry(
    paths: Iterable<[string, HitPath]>,
    hasVisitors: (code: string) => boolean,
    point: MapPoint,
    slop: number
): string | null {
    const entries = [...paths]
    const under = entries.find(([, path]) => path.contains(point.x, point.y))
    if (under) {
        const [code, path] = under
        if (hasVisitors(code)) {
            return code
        }
        const bounds = path.getBounds()
        if (Math.max(bounds.width, bounds.height) >= slop) {
            return null
        }
    }
    const candidates = entries.filter(([code]) => hasVisitors(code))
    for (const probe of rings(point, slop)) {
        const hit = candidates.find(([, path]) => path.contains(probe.x, probe.y))
        if (hit) {
            return hit[0]
        }
    }
    return null
}
