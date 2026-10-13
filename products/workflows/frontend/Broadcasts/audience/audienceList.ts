import { AnyPropertyFilter, PropertyFilterType } from '~/types'

import type { CohortApi } from 'products/cohorts/frontend/generated/api.schemas'

import type { PeopleImportApi } from '../../generated/api.schemas'
import type { AudienceCohort } from './broadcastAudienceCohortsLogic'

const SUPPORTED_ID_HEADERS = ['email', 'e-mail', 'distinct_id', 'distinct-id', 'person_id', 'person-id', 'person .id']

/**
 * Why the cohort import would reject this CSV, checked before anything is created, because a rejected
 * import still leaves an empty cohort behind. A single column without a known header is read as distinct IDs.
 */
export function csvListError(text: string): string | null {
    const lines = text.split(/\r?\n/).filter((line) => line.trim() !== '')
    if (lines.length === 0) {
        return 'The file is empty.'
    }
    const headers = splitCsvRow(lines[0]).map((header) => header.trim().toLowerCase())
    if (headers.length > 1 && !headers.some((header) => SUPPORTED_ID_HEADERS.includes(header))) {
        return 'The file needs a column named email, distinct_id or person_id.'
    }
    if (headers.some((header) => SUPPORTED_ID_HEADERS.includes(header)) && lines.length === 1) {
        return 'The file has a header row but no people in it.'
    }
    return null
}

function splitCsvRow(row: string): string[] {
    const fields: string[] = []
    let field = ''
    let quoted = false
    for (let i = 0; i < row.length; i++) {
        const char = row[i]
        if (quoted) {
            if (char === '"' && row[i + 1] === '"') {
                field += '"'
                i++
            } else if (char === '"') {
                quoted = false
            } else {
                field += char
            }
        } else if (char === '"') {
            quoted = true
        } else if (char === ',') {
            fields.push(field)
            field = ''
        } else {
            field += char
        }
    }
    fields.push(field)
    return fields
}

/**
 * Reads an uploaded list as UTF-8. The cohort import decodes the file strictly after it saves the cohort,
 * so a file in another encoding must fail here, before the cohort exists.
 */
export async function readCsvText(file: File): Promise<string> {
    const bytes = await file.arrayBuffer()
    try {
        return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    } catch {
        throw new Error('This file isn\'t saved as UTF-8. Save it as "CSV UTF-8" and upload it again.')
    }
}

/** Dated, so lists uploaded for the same broadcast stay apart in the cohorts list. */
export function defaultListCohortName(broadcastName: string, date: string): string {
    const name = broadcastName.trim()
    return `${name && name !== 'New broadcast' ? `${name} recipients` : 'Broadcast recipients'}, ${date}`
}

/** The cohorts an audience filters on, once each. */
export function audienceCohortIds(audienceProperties: AnyPropertyFilter[]): number[] {
    return [
        ...new Set(
            audienceProperties
                .filter((filter) => filter.type === PropertyFilterType.Cohort)
                .map((filter) => Number(filter.value))
                .filter((id) => Number.isFinite(id))
        ),
    ]
}

export function toAudienceCohort(id: number, cohort: CohortApi): AudienceCohort {
    return {
        id,
        name: cohort.name ?? `Cohort ${id}`,
        isStatic: !!cohort.is_static,
        isCalculating: !!cohort.is_calculating,
        failed: (cohort.errors_calculating ?? 0) > 0 && !cohort.is_calculating,
        count: cohort.count ?? null,
        importTotal: cohort.last_import_total_count ?? null,
        importUnmatched: cohort.last_import_unmatched_count ?? null,
    }
}

/**
 * Why a cohort in the audience stops a launch. A batch sends to the members a cohort has when it runs, so an
 * uploaded list that is still matching would reach only part of the list. A dynamic cohort keeps its members
 * while it recalculates, so it never blocks.
 */
export function audienceCohortLaunchError(cohort: AudienceCohort): string | null {
    if (!cohort.isStatic) {
        return null
    }
    if (cohort.isCalculating) {
        return `"${cohort.name}" is still matching people. You can launch when it finishes.`
    }
    if (cohort.failed) {
        return `"${cohort.name}" couldn't match its people. Remove it from the recipients, or upload the list again.`
    }
    return null
}

/** What an upload added, and which rows it skipped and why, so a short list is never a surprise. */
export function peopleImportMessage(cohortName: string, summary: PeopleImportApi): string {
    const parts = [`Added "${cohortName}" to the audience.`]
    if (summary.new_people) {
        parts.push(`${summary.new_people} new ${summary.new_people === 1 ? 'person was' : 'people were'} created.`)
    }
    const skipped: [number, string][] = [
        [summary.dropped_invalid_email, 'had no valid email'],
        [summary.dropped_duplicate_email, 'repeated an email or distinct ID'],
        [summary.dropped_too_large, 'held more than 4KB of data'],
    ]
    const reasons = skipped.filter(([count]) => count > 0).map(([count, reason]) => `${count} ${reason}`)
    const skippedRows = skipped.reduce((total, [count]) => total + count, 0)
    if (skippedRows) {
        parts.push(`Skipped ${skippedRows} ${skippedRows === 1 ? 'row' : 'rows'}: ${reasons.join(', ')}.`)
    }
    parts.push('Their properties can take a minute to update.')
    return parts.join(' ')
}
