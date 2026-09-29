// The id columns the cohort CSV import reads. A list is one kind or the other, never both.
export type AudienceListIdType = 'email' | 'distinct_id'

export interface AudienceList {
    idType: AudienceListIdType
    entries: string[]
    duplicatesRemoved: number
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/**
 * Reads a pasted list of people: one per line, or separated by commas or semicolons, the way it comes out of a
 * spreadsheet column or an email client. Emails are lowercased, because the cohort import matches them exactly
 * and stored emails are almost always lowercase.
 */
export function parseAudienceList(text: string): AudienceList {
    const raw = text
        .split(/[\n,;]+/)
        .map((entry) => entry.trim().replace(/^["']|["']$/g, ''))
        .filter(Boolean)
    const idType: AudienceListIdType =
        raw.length > 0 && raw.every((entry) => EMAIL_PATTERN.test(entry)) ? 'email' : 'distinct_id'
    const entries = [...new Set(idType === 'email' ? raw.map((entry) => entry.toLowerCase()) : raw)]
    return { idType, entries, duplicatesRemoved: raw.length - entries.length }
}

function csvCell(value: string): string {
    return /[",\n\r]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

/** The pasted list as the CSV file the cohort import expects, with the id type as its header. */
export function audienceListCsv(list: AudienceList): File {
    const rows = [list.idType, ...list.entries.map(csvCell)]
    return new File([rows.join('\n') + '\n'], 'broadcast-audience.csv', { type: 'text/csv' })
}

const SUPPORTED_ID_HEADERS = ['email', 'e-mail', 'distinct_id', 'distinct-id', 'person_id', 'person .id']

/**
 * Why the cohort import would reject this CSV, checked before anything is created, because a rejected
 * import still leaves an empty cohort behind. A single column without a known header is read as distinct IDs.
 */
export function csvListError(text: string): string | null {
    const lines = text.split(/\r?\n/).filter((line) => line.trim() !== '')
    if (lines.length === 0) {
        return 'The file is empty.'
    }
    const headers = lines[0].split(',').map((header) => header.trim().replace(/^"|"$/g, '').toLowerCase())
    if (headers.length > 1 && !headers.some((header) => SUPPORTED_ID_HEADERS.includes(header))) {
        return 'The file needs a column named email, distinct_id or person_id.'
    }
    if (headers.some((header) => SUPPORTED_ID_HEADERS.includes(header)) && lines.length === 1) {
        return 'The file has a header row but no people in it.'
    }
    return null
}

/** Dated, so lists uploaded for the same broadcast stay apart in the cohorts list. */
export function defaultListCohortName(broadcastName: string, date: string): string {
    const name = broadcastName.trim()
    return `${name && name !== 'New broadcast' ? `${name} recipients` : 'Broadcast recipients'}, ${date}`
}
