import type { ActorsAtPointInput } from '@/api/actors'
import { asRecord } from '@/lib/records'
import type { ActorRow, InsightSnapshot } from '@/model/views'

import { seriesForKey } from '../snapshotChart'

/**
 * The actors query for one series at one bucket. The source is the response's `query.source`, with the dashboard and
 * tile layers applied, so the people match the chart. Null when the series has no bucket at that index.
 */
export function pointActorsInput(
    snapshot: InsightSnapshot,
    seriesKey: string,
    index: number,
    includeRecordings: boolean
): ActorsAtPointInput | null {
    const series = seriesForKey(snapshot, seriesKey)
    const day = series?.points[index]?.at
    if (!series || !day) {
        return null
    }
    const query = asRecord(snapshot.query)
    return {
        source: query?.source ?? snapshot.query,
        day,
        series: series.seriesIndex,
        breakdown: series.breakdownValue,
        compare: series.compare,
        includeRecordings,
    }
}

export interface RecordingRow {
    key: string
    personName: string
    sessionId: string
    /** "Recording 2 of 3" when the person has more than one. */
    position: string | null
}

/** One row per matched recording, in the people's order. */
export function recordingRows(people: readonly ActorRow[]): RecordingRow[] {
    return people.flatMap((person) =>
        person.recordings.map((sessionId, index) => ({
            key: `${person.id}:${sessionId}`,
            personName: person.name,
            sessionId,
            position: person.recordings.length > 1 ? `Recording ${index + 1} of ${person.recordings.length}` : null,
        }))
    )
}
