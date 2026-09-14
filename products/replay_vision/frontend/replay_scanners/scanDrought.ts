import { ObservationVersionMarkerApi } from '../generated/api.schemas'

// A full day, so a fresh edit gets time to produce observations before we call it a drought.
export const SCAN_DROUGHT_MIN_AGE_MS = 24 * 60 * 60 * 1000

export interface ScanDroughtScannerFields {
    enabled: boolean
    limit_reached: boolean
    scanner_version: number
    sampling_rate: number
    updated_at: string
    last_swept_at: string
}

export interface ScanDrought {
    /** False when no version has ever produced an observation, so the copy can say "yet" instead of "since the change". */
    everScanned: boolean
    samplingRate: number
}

/** A version marker exists for any version with at least one observation of any status, so no marker for the
 * current version means sweeps enqueued nothing at all — the filters matched no recordings or sampling skipped
 * them, which users otherwise misread as the product being broken. */
export function scanDrought(
    scanner: ScanDroughtScannerFields,
    versionMarkers: ObservationVersionMarkerApi[] | null,
    now: Date
): ScanDrought | null {
    // sampling_rate 0 is the documented way to pause scanning, so no observations is expected then.
    if (!versionMarkers || !scanner.enabled || scanner.limit_reached || scanner.sampling_rate === 0) {
        return null
    }
    if (versionMarkers.some((marker) => marker.version === scanner.scanner_version)) {
        return null
    }
    // updated_at also advances on metadata-only edits (name, description), re-arming the gates below
    // and hiding an active warning for up to a day. Accepted: the scanner carries no version-change
    // timestamp, and this errs toward silence, never toward a false warning.
    const updatedAt = new Date(scanner.updated_at).getTime()
    if (now.getTime() - updatedAt < SCAN_DROUGHT_MIN_AGE_MS) {
        return null
    }
    // The sweep watermark trails wallclock by the settle window, so this only fires once sweeps have
    // actually covered sessions that ended after the last save.
    if (new Date(scanner.last_swept_at).getTime() <= updatedAt) {
        return null
    }
    return { everScanned: versionMarkers.length > 0, samplingRate: scanner.sampling_rate }
}
