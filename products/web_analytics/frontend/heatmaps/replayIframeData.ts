import { z } from 'zod'

import { uuid } from 'lib/utils/dom'
import { localStorageSlot } from 'lib/utils/localStorageSlot'

export interface ReplayIframeData {
    html: string
    width: number // NB this should be meta width
    height: number // NB this should be meta height
    startDateTime: string | undefined
    url: string | undefined
}

export const ReplayIframeDatakeyPrefix = 'ph_replay_fixed_heatmap_'

// Recordings with no captured href get the synthesized 'unknown', which a heatmap query cannot use.
export function isUsableHeatmapUrl(url: string | undefined | null): url is string {
    const trimmed = url?.trim()
    return !!trimmed && trimmed !== 'unknown'
}

function isAbsoluteUrl(url: string): boolean {
    try {
        new URL(url)
        return url.includes('://')
    } catch {
        return false
    }
}

/**
 * Give a recorded href an origin, so a heatmap query can match it.
 *
 * A snapshot can carry a path instead of a full address. Heatmap data holds the absolute page
 * address, so a path matches nothing. Each base is an address from the same recording, best
 * candidate first. A path that no base can complete stays as it is, for the person to correct.
 */
export function resolveHeatmapUrl(
    url: string | undefined | null,
    bases: (string | undefined | null)[]
): string | undefined {
    const trimmed = url?.trim()
    if (!isUsableHeatmapUrl(trimmed)) {
        return undefined
    }
    if (isAbsoluteUrl(trimmed)) {
        return trimmed
    }
    for (const base of bases) {
        const trimmedBase = base?.trim()
        if (!trimmedBase || !isAbsoluteUrl(trimmedBase)) {
            continue
        }
        try {
            return new URL(trimmed, trimmedBase).toString()
        } catch {
            continue
        }
    }
    return trimmed
}

// Serializing the replayed DOM allocates several full copies of this on the main thread, in a tab
// that is already holding a decoded recording. Past roughly this size that spike is what kills the
// renderer.
export const MAX_REPLAY_IFRAME_HTML_CHARS = 2_000_000

const replayIframeDataSchema = z.object({
    html: z.string().refine((html) => !!html.trim()),
    width: z.number(),
    height: z.number(),
    startDateTime: z.union([z.string(), z.undefined()]),
    url: z.union([z.string(), z.undefined()]),
})

export function removeReplayIframeDataFromLocalStorage(exceptKey?: string): void {
    for (let i = localStorage.length - 1; i >= 0; i--) {
        const key = localStorage.key(i)
        if (key?.startsWith(ReplayIframeDatakeyPrefix) && key !== exceptKey) {
            localStorage.removeItem(key)
        }
    }
}

export function persistReplayIframeData(data: ReplayIframeData): string | null {
    const key = ReplayIframeDatakeyPrefix + uuid()
    try {
        localStorage.setItem(key, JSON.stringify(data))
    } catch {
        return null
    }
    // prune only after a successful write, so a failed write leaves the previous key usable
    removeReplayIframeDataFromLocalStorage(key)
    return key
}

// a missing or malformed snapshot must resolve to null rather than throwing, so callers land on the
// recording fallback instead of unwinding out of a router listener with the scene half-mounted
export function getStoredRecordingBackground(storageKey: string | null): ReplayIframeData | null {
    return storageKey ? localStorageSlot(storageKey, replayIframeDataSchema).get() : null
}
