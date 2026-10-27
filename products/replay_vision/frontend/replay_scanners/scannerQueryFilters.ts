import {
    convertUniversalFiltersToRecordingsQuery,
    recordingsQueryToUniversalFilters,
} from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { stripSessionIds } from 'scenes/session-recordings/playlist/playlistUtils'
import { asUniversalFilters } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { RecordingsQuery } from '~/queries/schema/schema-general'
import { RecordingUniversalFilters, SessionRecordingPlaylistType } from '~/types'

import { clampDurationFilter } from './durationBounds'

/**
 * Writes the filter dimensions that the scanner's recording filters editor renders onto the query.
 * Other query fields survive, because the editor does not show them and must not reset them.
 */
export function overlayEditorFilters(
    query: RecordingsQuery | null,
    filters: RecordingUniversalFilters
): RecordingsQuery {
    const converted = convertUniversalFiltersToRecordingsQuery(filters)
    return {
        ...query,
        kind: converted.kind,
        events: converted.events,
        actions: converted.actions,
        properties: converted.properties,
        console_log_filters: converted.console_log_filters,
        having_predicates: converted.having_predicates,
        comment_text: converted.comment_text,
        filter_test_accounts: converted.filter_test_accounts,
        operand: converted.operand,
    }
}

export type SavedFilterApplication =
    | { status: 'applied'; query: RecordingsQuery }
    | { status: 'experiment-filter' }
    | { status: 'no-filters' }

/**
 * Copies a replay saved filter onto a scanner query. Later edits to the saved filter do not reach the
 * scanner. The overlay drops pinned session ids and the date range, because a scanner scans new sessions
 * on its own schedule.
 */
export function applySavedFilterToScannerQuery(
    query: RecordingsQuery | null,
    savedFilter: Pick<SessionRecordingPlaylistType, 'filters'>
): SavedFilterApplication {
    const universal = asUniversalFilters(savedFilter.filters)
    if (!universal) {
        return { status: 'no-filters' }
    }
    const filters = stripSessionIds(universal)
    // The overlay has no place for experiment exposure. Dropping it in silence would widen the scanner
    // to sessions outside the experiment, so the caller refuses this saved filter instead.
    if (filters.experiment_exposure) {
        return { status: 'experiment-filter' }
    }
    // A saved filter can leave out parts, such as the duration. Those parts keep the scanner's current
    // values, the same as when the replay page applies a saved filter.
    const merged: RecordingUniversalFilters = {
        ...recordingsQueryToUniversalFilters(query),
        ...(Object.fromEntries(
            Object.entries(filters).filter(([, value]) => value !== undefined)
        ) as Partial<RecordingUniversalFilters>),
    }
    return {
        status: 'applied',
        query: overlayEditorFilters(query, { ...merged, duration: merged.duration.map(clampDurationFilter) }),
    }
}
