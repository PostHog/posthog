import Papa from 'papaparse'

// The API accepts request bodies up to 20MB. The rows go up as JSON, which is larger than the CSV.
const MAX_REQUEST_BYTES = 19 * 1024 * 1024

/** Reads a CSV of people into rows. Throws a message for the uploader when the file cannot be used. */
export function parsePeopleCsv(text: string): Record<string, string>[] {
    // Papa's header mode rewrites repeated headers from a naive split of the first line, which breaks quoted
    // headers that contain the delimiter. One parse into arrays keeps the headers exactly as the file has them.
    const { data, errors } = Papa.parse<string[]>(text, { skipEmptyLines: true })
    // A row with an unclosed quote puts values under the wrong columns.
    // Papa also reports that it could not detect a delimiter in a one-column file, which is not an error.
    const problem = errors.find((error) => error.type === 'Quotes')
    if (problem) {
        throw new Error(`Row ${(problem.row ?? 0) + 1} of the file can't be read: ${problem.message}.`)
    }
    const [headers = [], ...rows] = data
    // Two columns with one name would collapse into one key, so the API could not see the repeat.
    const repeated = headers.find((header, index) => header.trim() !== '' && headers.indexOf(header) !== index)
    if (repeated !== undefined) {
        throw new Error(`Two columns are both named "${repeated}". Rename one and try again.`)
    }
    const people = rows.map((cells, index) => {
        if (cells.length !== headers.length) {
            throw new Error(
                `Row ${index + 2} of the file has ${cells.length} values, but the first row has ${headers.length} column names. Fix the row and try again.`
            )
        }
        const person: Record<string, string> = {}
        headers.forEach((header, column) => {
            if (header.trim() !== '') {
                person[header] = cells[column]
            } else if (cells[column].trim() !== '') {
                throw new Error('A column with data in it has no name. Name it and try again.')
            }
        })
        return person
    })
    if (new Blob([JSON.stringify(people)]).size > MAX_REQUEST_BYTES) {
        throw new Error('This file is too large to upload. Remove some rows or columns and try again.')
    }
    return people
}
