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
 * scaled first and translated second.
 */
export function mapTransform(fit: MapFit): MapTransform {
    return [{ translateX: -WORLD_CROP.x * fit.scale }, { translateY: -WORLD_CROP.y * fit.scale }, { scale: fit.scale }]
}
