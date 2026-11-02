import { objectsEqual } from 'lib/utils/objects'

import { SignalReport } from '../types'

type ReportCopy = Pick<SignalReport, 'id' | 'assignee' | 'priority'>
type WrittenFields = Partial<Pick<SignalReport, 'assignee' | 'priority'>>

function fieldsWrittenBetween(before: ReportCopy, current: ReportCopy): WrittenFields {
    const written: WrittenFields = {}
    if (!objectsEqual(current.assignee ?? null, before.assignee ?? null)) {
        written.assignee = current.assignee
    }
    if (current.priority !== before.priority) {
        written.priority = current.priority
    }
    return written
}

/**
 * A claim or a priority edit patches the local copy of a report while a fetch for it is in flight. The fetch can
 * have read the report before that write saved, and a claim does not change `updated_at`, so the response can't be
 * ordered by timestamp. Compare the copy from before the fetch with the copy now, and keep each field that the page
 * wrote in between.
 */
export function keepFieldsWrittenDuringFetch<T extends ReportCopy>(
    fetched: T,
    before: ReportCopy | null | undefined,
    current: ReportCopy | null | undefined
): T {
    if (!before || !current || current === before) {
        return fetched
    }
    if (before.id !== fetched.id || current.id !== fetched.id) {
        return fetched
    }
    const written = fieldsWrittenBetween(before, current)
    return Object.keys(written).length > 0 ? { ...fetched, ...written } : fetched
}

/** {@link keepFieldsWrittenDuringFetch} for each row of a fetched list. */
export function keepRowFieldsWrittenDuringFetch<T extends ReportCopy>(
    fetched: T[],
    before: ReportCopy[] | null | undefined,
    current: ReportCopy[] | null | undefined
): T[] {
    if (!before || !current || before === current) {
        return fetched
    }
    const beforeById = new Map(before.map((row) => [row.id, row]))
    const currentById = new Map(current.map((row) => [row.id, row]))
    return fetched.map((row) => keepFieldsWrittenDuringFetch(row, beforeById.get(row.id), currentById.get(row.id)))
}
