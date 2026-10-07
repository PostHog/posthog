import Papa from 'papaparse'

// The API accepts request bodies up to 20MB. The rows go up as JSON, which is larger than the CSV.
const MAX_REQUEST_BYTES = 19 * 1024 * 1024

/** Reads a recipient CSV into rows. Throws a message for the uploader when the file cannot be used. */
export function parseRecipientCsv(text: string): Record<string, string>[] {
    // With header: true, Papa renames a repeated header to name_1 or keeps only the last value, and reports no error.
    // The API then can't see the repeat, and the broadcast uses one of the two columns without a warning.
    const [headers = []] = Papa.parse<string[]>(text, { preview: 1 }).data
    const repeated = headers.find((header, index) => header.trim() !== '' && headers.indexOf(header) !== index)
    if (repeated !== undefined) {
        throw new Error(`Two columns are both named "${repeated}". Rename one and try again.`)
    }
    const { data, errors } = Papa.parse<Record<string, string>>(text, { header: true, skipEmptyLines: true })
    // A row with an unclosed quote or the wrong number of cells puts values under the wrong columns.
    // Papa also reports that it could not detect a delimiter in a one-column file, which is not an error.
    const problem = errors.find((error) => error.type === 'Quotes' || error.type === 'FieldMismatch')
    if (problem) {
        throw new Error(`Row ${(problem.row ?? 0) + 2} of the file can't be read: ${problem.message}.`)
    }
    if (new Blob([JSON.stringify(data)]).size > MAX_REQUEST_BYTES) {
        throw new Error('This list is too large to upload. Remove some rows or columns and try again.')
    }
    return data
}
