/** A region of the map's viewBox, in map units. */
export interface MapCrop {
    x: number
    y: number
    width: number
    height: number
}

/** The world without the empty Pacific margins of the source viewBox. */
export const WORLD_CROP: MapCrop = { x: 90, y: 16, width: 2580, height: 1156 }

export function mapAspectRatio(crop: MapCrop): number {
    return crop.width / crop.height
}

export interface MapFit {
    crop: MapCrop
    /** Points per map unit. */
    scale: number
    height: number
}

/** Fits `crop` to `width` points, keeping its aspect ratio. */
export function fitMap(crop: MapCrop, width: number): MapFit {
    const scale = width / crop.width
    return { crop, scale, height: crop.height * scale }
}

export interface MapPoint {
    x: number
    y: number
}

/** A point in the map's box, in points from its top left, as a point in map units. */
export function toMapPoint(fit: MapFit, x: number, y: number): MapPoint {
    return { x: x / fit.scale + fit.crop.x, y: y / fit.scale + fit.crop.y }
}

export interface HitPath {
    contains: (x: number, y: number) => boolean
}

const RING_STEPS = 8

/** The tap point, then eight points at half the slop and eight at the full slop around it. */
function probes(point: MapPoint, slop: number): MapPoint[] {
    const around = (radius: number): MapPoint[] =>
        Array.from({ length: RING_STEPS }, (_, step) => {
            const angle = (step / RING_STEPS) * 2 * Math.PI
            return { x: point.x + radius * Math.cos(angle), y: point.y + radius * Math.sin(angle) }
        })
    return slop > 0 ? [point, ...around(slop / 2), ...around(slop)] : [point]
}

/**
 * The country under a tap, or null. Small countries are a few points wide on a phone, so a tap that misses every
 * shape also tries points up to `slop` map units away, nearest first.
 */
export function pickCountry(paths: Iterable<[string, HitPath]>, point: MapPoint, slop: number): string | null {
    const entries = [...paths]
    for (const probe of probes(point, slop)) {
        const hit = entries.find(([, path]) => path.contains(probe.x, probe.y))
        if (hit) {
            return hit[0]
        }
    }
    return null
}
