import { gunzipSync, gzipSync, strFromU8, strToU8 } from 'fflate'
import { z } from 'zod'

import { uuid } from 'lib/utils/dom'

export interface ReplayIframeData {
    html: string
    width: number // NB this should be meta width
    height: number // NB this should be meta height
    startDateTime: string | undefined
    url: string | undefined
}

export const ReplayIframeDatakeyPrefix = 'ph_replay_fixed_heatmap_'

// The snapshot travels to the heatmap scene through localStorage, which browsers cap near 5 MB per
// origin. Real pages reach several million characters, so the uncompressed JSON does not fit. We
// gzip the snapshot before writing, which shrinks a normal page well under the quota. This ceiling
// stays only as a backstop, so one pathological page cannot spike the main thread during capture.
export const MAX_REPLAY_IFRAME_HTML_CHARS = 20_000_000

const replayIframeDataSchema = z.object({
    html: z.string().refine((html) => !!html.trim()),
    width: z.number(),
    height: z.number(),
    startDateTime: z.union([z.string(), z.undefined()]),
    url: z.union([z.string(), z.undefined()]),
})

// gzip the JSON and keep the bytes as a latin1 string, so localStorage holds one code unit per byte
function compressReplayIframeData(data: ReplayIframeData): string {
    return strFromU8(gzipSync(strToU8(JSON.stringify(data))), true)
}

function decompressReplayIframeData(stored: string): unknown {
    return JSON.parse(strFromU8(gunzipSync(strToU8(stored, true))))
}

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
    // prune stale snapshots before writing, so a quota failure frees space and the next attempt can recover
    removeReplayIframeDataFromLocalStorage()
    try {
        localStorage.setItem(key, compressReplayIframeData(data))
    } catch {
        return null
    }
    return key
}

// a missing or malformed snapshot must resolve to null rather than throwing, so callers land on the
// recording fallback instead of unwinding out of a router listener with the scene half-mounted
export function getStoredRecordingBackground(storageKey: string | null): ReplayIframeData | null {
    if (!storageKey) {
        return null
    }
    try {
        const stored = localStorage.getItem(storageKey)
        if (!stored) {
            return null
        }
        const result = replayIframeDataSchema.safeParse(decompressReplayIframeData(stored))
        return result.success ? result.data : null
    } catch {
        return null
    }
}
