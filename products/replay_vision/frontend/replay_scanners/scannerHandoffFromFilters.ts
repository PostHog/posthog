import { objectsEqual } from 'lib/utils/objects'
import { convertUniversalFiltersToRecordingsQuery } from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { stripSessionIds } from 'scenes/session-recordings/playlist/playlistUtils'
import { defaultRecordingDurationFilter } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { filtersFromUniversalFilterGroups } from 'scenes/session-recordings/utils'

import type { RecordingUniversalFilters } from '~/types'

import { experimentScannerParams } from './experimentTargeting'

/** The wizard hand-off for "create a scanner from these replay filters". */
export interface ScannerHandoffFromFilters {
    /** Params for the new-scanner wizard URL: the encoded query, plus experiment targeting when the filters carry it. */
    searchParams: Record<string, string>
    /**
     * Whether the resulting scanner would watch a subset of sessions rather than all of them.
     *
     * Deliberately not the replay list's filter count, which also counts the date range and pinned
     * session IDs. A scanner keeps neither, so counting them offers a one-click path to a scanner
     * aimed at every session.
     */
    narrowsSessions: boolean
}

/**
 * Converts the replay list's filters into the scanner the wizard should open with.
 *
 * A scanner keeps less of a filter set than this panel does, and each difference fails silently:
 * the dropped pieces save into a scanner that matches nothing, or one that matches everything, and
 * both look healthy in the scanner list. So the lossy fields are resolved here rather than at the
 * call site.
 *
 * - Session IDs pin the query to recordings that already exist. Nothing downstream removes them and
 *   the sweep only moves forward, so a scanner carrying them never matches again.
 * - Experiment exposure is rejected inside `query` by the API, which resolves it from
 *   `experiment_targeting` at scan time so the experiment stays behind that field's access check.
 *   Left in, the wizard can't be saved; dropped, the scanner silently widens past the experiment.
 *   It becomes the wizard's experiment deep link instead, which carries the same targeting the
 *   experiment's own entry point uses.
 * - The date range is dropped by the backend on save, because a scanner's schedule owns time.
 */
export function scannerHandoffFromFilters(filters: RecordingUniversalFilters): ScannerHandoffFromFilters {
    const { experiment_exposure: exposure, ...query } = convertUniversalFiltersToRecordingsQuery(
        stripSessionIds(filters)
    )

    return {
        searchParams: {
            filters: JSON.stringify(query),
            ...(exposure
                ? experimentScannerParams({
                      experimentId: exposure.experiment_id,
                      variantKey: exposure.variant ?? null,
                  })
                : {}),
        },
        narrowsSessions:
            filtersFromUniversalFilterGroups(filters).length > 0 ||
            // Every filter set carries a duration floor, so only one the user moved off the default
            // counts as narrowing.
            (filters.duration ?? []).some((predicate) => !objectsEqual(predicate, defaultRecordingDurationFilter)) ||
            !!exposure,
    }
}
