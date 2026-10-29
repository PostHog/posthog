import {
    convertUniversalFiltersToRecordingsQuery,
    recordingsQueryToUniversalFilters,
} from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { stripSessionIds } from 'scenes/session-recordings/playlist/playlistUtils'
import { asUniversalFilters } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { RecordingsQuery } from '~/queries/schema/schema-general'
import { RecordingUniversalFilters, SessionRecordingPlaylistType } from '~/types'

import { clampDurationFilter } from './durationBounds'

/** Writes only the dimensions the scanner's filter editor shows, so fields it hides survive an edit. */
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

export function applySavedFilterToScannerQuery(
    query: RecordingsQuery | null,
    savedFilter: Pick<SessionRecordingPlaylistType, 'filters'>
): SavedFilterApplication {
    const universal = asUniversalFilters(savedFilter.filters)
    if (!universal) {
        return { status: 'no-filters' }
    }
    const filters = stripSessionIds(universal)
    // The query cannot hold experiment exposure, and dropping it would scan sessions outside the experiment.
    if (filters.experiment_exposure) {
        return { status: 'experiment-filter' }
    }
    // Parts the saved filter leaves out keep their current values, as on the replay page.
    const merged: RecordingUniversalFilters = {
        ...recordingsQueryToUniversalFilters(query),
        ...(Object.fromEntries(
            Object.entries(filters).filter(([, value]) => value !== undefined)
        ) as Partial<RecordingUniversalFilters>),
    }
    return {
        status: 'applied',
        query: {
            ...overlayEditorFilters(query, { ...merged, duration: merged.duration.map(clampDurationFilter) }),
            // The editor hides these selection settings, but scans still apply them.
            recommended_only: merged.recommended_only,
            event_match_scope: merged.event_match_scope,
        },
    }
}
