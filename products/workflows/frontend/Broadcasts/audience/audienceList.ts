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
