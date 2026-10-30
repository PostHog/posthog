import { isCommentTextFilter } from 'lib/components/UniversalFilters/utils'
import { objectsEqual } from 'lib/utils/objects'
import { convertUniversalFiltersToRecordingsQuery } from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { stripSessionIds } from 'scenes/session-recordings/playlist/playlistUtils'
import { defaultRecordingDurationFilter } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { filtersFromUniversalFilterGroups } from 'scenes/session-recordings/utils'

import type { RecordingsQuery } from '~/queries/schema/schema-general'
import type { RecordingUniversalFilters } from '~/types'

import { type ExperimentScannerParams, experimentScannerParams } from './experimentTargeting'

/** The wizard hand-off for "create a scanner from these replay filters". */
export interface ScannerHandoffFromFilters {
    /** Params for the new-scanner wizard URL: the encoded query, plus experiment targeting when the filters carry it. */
    searchParams: Record<string, string>
    query: RecordingsQuery
    /** The filter as the person chose it, exposure included, which the AI draft turns into the scanner's experiment. */
    chosenQuery: RecordingsQuery
    /** Experiment exposure from the filters, which a scanner keeps as targeting rather than inside `query`. */
    experiment: ExperimentScannerParams | null
    pinnedSessionCount: number
    droppedCommentSearch: boolean
    /**
     * Whether the resulting scanner would watch a subset of sessions rather than all of them.
     *
     * Deliberately not the replay list's filter count, which also counts the date range and pinned
     * session IDs. A scanner keeps neither, so counting them would tell the person their scanner is
     * narrowed when it actually watches every session.
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
 * - Experiment exposure is rejected inside `query` by the API, which resolves it from the
 *   experiment scanner's config at scan time so the experiment stays behind its access check.
 *   Left in, the wizard can't be saved; dropped, the scanner silently widens past the experiment.
 *   It becomes the wizard's experiment deep link instead, which builds the same experiment
 *   scanner the experiment's own entry point does.
 * - The date range is dropped by the backend on save, because a scanner's schedule owns time.
 * - Only the replay list API applies the comment search and "hide viewed recordings", so a scanner
 *   that kept them would watch more than the person chose. They are dropped here, where the person is told.
 */
export function scannerHandoffFromFilters(filters: RecordingUniversalFilters): ScannerHandoffFromFilters {
    const {
        experiment_exposure: exposure,
        comment_text: commentText,
        hide_viewed_recordings: _hideViewedRecordings,
        ...query
    } = convertUniversalFiltersToRecordingsQuery(stripSessionIds(filters))

    const experiment = exposure ? { experimentId: exposure.experiment_id, variantKey: exposure.variant ?? null } : null

    return {
        searchParams: {
            filters: JSON.stringify(query),
            ...(experiment ? experimentScannerParams(experiment) : {}),
        },
        query,
        chosenQuery: exposure ? { ...query, experiment_exposure: exposure } : query,
        experiment,
        pinnedSessionCount: filters.session_ids?.length ?? 0,
        droppedCommentSearch: !!commentText,
        narrowsSessions:
            filtersFromUniversalFilterGroups(filters).some((filter) => !isCommentTextFilter(filter)) ||
            // Every filter set carries a duration floor, so only one the user moved off the default
            // counts as narrowing.
            (filters.duration ?? []).some((predicate) => !objectsEqual(predicate, defaultRecordingDurationFilter)) ||
            !!exposure,
    }
}
