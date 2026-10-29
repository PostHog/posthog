import Papa from 'papaparse'

import { ApiError } from 'lib/api'

import type {
    PushTokenImportFailureApi,
    PushTokenImportResponseApi,
    PushTokenSubscriptionApi,
} from 'products/integrations/frontend/generated/api.schemas'
import { PushTokenImportFailureReasonEnumApi } from 'products/integrations/frontend/generated/api.schemas'

// Limits of the import endpoint. A request over them is refused as a whole.
export const ROWS_PER_REQUEST = 1000
// Parsing runs on the page, so a file this size still previews in a second or two.
export const MAX_FILE_BYTES = 20 * 1024 * 1024
const MAX_DISTINCT_ID_LENGTH = 200
const MAX_DEVICE_TOKEN_LENGTH = 4096

// A stalled request is given up and retried, like a network error.
const REQUEST_TIMEOUT_MS = 60_000
const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000]
const MAX_RATE_LIMIT_WAITS = 10
const DEFAULT_RATE_LIMIT_WAIT_MS = 10_000
const MAX_RATE_LIMIT_WAIT_MS = 60_000

export interface PushTokenRow extends PushTokenSubscriptionApi {
    /** Line in the uploaded file, counting the header as line 1. */
    line: number
}

export interface FailedPushTokenRow extends PushTokenRow {
    /** Plain sentence shown to the person importing. */
    reason: string
    /** Set when no person had the distinct ID, so the row can be imported again with new persons. */
    unknownPerson?: boolean
}

export interface ParsedPushTokenCsv {
    rows: PushTokenRow[]
    rejected: FailedPushTokenRow[]
    duplicates: number
}

export interface PushTokenImportOutcome {
    imported: number
    failed: FailedPushTokenRow[]
    /** Set when the import stopped before sending every row. */
    stoppedReason: string | null
}

export type SendPushTokens = (
    subscriptions: PushTokenSubscriptionApi[],
    options: { create_missing_persons: boolean },
    signal: AbortSignal
) => Promise<PushTokenImportResponseApi>

export type Sleep = (ms: number, signal: AbortSignal) => Promise<void>

/** Waits, but returns as soon as the import is stopped. */
export const sleepUnlessAborted: Sleep = (ms, signal) =>
    new Promise((resolve) => {
        const timer = setTimeout(done, ms)
        function done(): void {
            clearTimeout(timer)
            signal.removeEventListener('abort', done)
            resolve()
        }
        signal.addEventListener('abort', done)
    })

class ImportStopped extends Error {}

const SERVER_REASONS: Record<PushTokenImportFailureApi['reason'], string> = {
    [PushTokenImportFailureReasonEnumApi.UnknownPerson]: 'No person has this distinct ID',
    [PushTokenImportFailureReasonEnumApi.TokenMismatch]: "The token doesn't fit this channel",
    [PushTokenImportFailureReasonEnumApi.NotStored]: 'Not stored, import it again',
    [PushTokenImportFailureReasonEnumApi.PersonProcessingDisabled]: 'Person processing is off for this person',
}

function rejectReason(distinctId: string, deviceToken: string): string | null {
    if (!distinctId) {
        return 'No distinct ID'
    }
    if (!deviceToken) {
        return 'No device token'
    }
    if (distinctId.length > MAX_DISTINCT_ID_LENGTH) {
        return `Distinct ID is longer than ${MAX_DISTINCT_ID_LENGTH} characters`
    }
    if (deviceToken.length > MAX_DEVICE_TOKEN_LENGTH) {
        return `Device token is longer than ${MAX_DEVICE_TOKEN_LENGTH} characters`
    }
    return null
}

/** Reads a CSV with a header row into devices to import. Throws a message for the uploader when the file cannot be used. */
export function parsePushTokenCsv(text: string): ParsedPushTokenCsv {
    const { data, errors } = Papa.parse<string[]>(text)
    const problem = errors.find((error) => error.type === 'Quotes')
    if (problem) {
        throw new Error(`Line ${(problem.row ?? 0) + 1} of the file can't be read: ${problem.message}.`)
    }
    const [headers = [], ...lines] = data
    const columns = headers.map((header) => header.trim().toLowerCase())
    const distinctIdColumn = columns.indexOf('distinct_id')
    const deviceTokenColumn = columns.indexOf('device_token')
    if (distinctIdColumn === -1 || deviceTokenColumn === -1) {
        throw new Error(
            'The first line of the file must name the columns, and it needs a distinct_id column and a device_token column.'
        )
    }
    if (lines.every((cells) => cells.every((cell) => cell.trim() === ''))) {
        throw new Error('The file has no devices in it, only the column names.')
    }

    const rows: PushTokenRow[] = []
    const rejected: FailedPushTokenRow[] = []
    const seen = new Set<string>()
    let duplicates = 0
    lines.forEach((cells, index) => {
        if (cells.every((cell) => cell.trim() === '')) {
            return
        }
        const line = index + 2
        const distinctId = (cells[distinctIdColumn] ?? '').trim()
        const deviceToken = (cells[deviceTokenColumn] ?? '').trim()
        const reason = rejectReason(distinctId, deviceToken)
        if (reason) {
            rejected.push({ line, distinct_id: distinctId, device_token: deviceToken, reason })
            return
        }
        const key = `${distinctId}\n${deviceToken}`
        if (seen.has(key)) {
            duplicates++
            return
        }
        seen.add(key)
        rows.push({ line, distinct_id: distinctId, device_token: deviceToken })
    })
    return { rows, rejected, duplicates }
}

export function chunkRows<T>(rows: T[]): T[][] {
    const chunks: T[][] = []
    for (let start = 0; start < rows.length; start += ROWS_PER_REQUEST) {
        chunks.push(rows.slice(start, start + ROWS_PER_REQUEST))
    }
    return chunks
}

/** Matches the API's failures, which carry only a token suffix, back to the rows that were sent. */
function failedRowsOf(chunk: PushTokenRow[], failures: PushTokenImportFailureApi[]): FailedPushTokenRow[] {
    const unmatched = [...chunk]
    const failed: FailedPushTokenRow[] = []
    for (const failure of failures) {
        const index = unmatched.findIndex(
            (row) => row.distinct_id === failure.distinct_id && row.device_token.endsWith(failure.device_token_suffix)
        )
        if (index === -1) {
            continue
        }
        const [row] = unmatched.splice(index, 1)
        failed.push({
            ...row,
            // The API's sentence for a token mismatch names the token it saw, such as an Expo token.
            reason:
                failure.reason === PushTokenImportFailureReasonEnumApi.TokenMismatch
                    ? failure.detail
                    : (SERVER_REASONS[failure.reason] ?? failure.detail),
            unknownPerson: failure.reason === PushTokenImportFailureReasonEnumApi.UnknownPerson,
        })
    }
    return failed
}

function rateLimitWaitMs(error: ApiError): number {
    const retryAfter = Number(error.headers?.get('Retry-After'))
    if (Number.isFinite(retryAfter) && retryAfter > 0) {
        return Math.min(retryAfter * 1000, MAX_RATE_LIMIT_WAIT_MS)
    }
    return DEFAULT_RATE_LIMIT_WAIT_MS
}

function isRetryable(error: unknown): boolean {
    // A request that timed out rejects with the timeout's reason rather than an ApiError.
    if (!(error instanceof ApiError)) {
        return error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError')
    }
    // A network error carries no status.
    return error.status === undefined || error.status >= 500
}

/** A rejected request that no other row would get past, such as missing permission. */
function stopsImport(error: unknown): boolean {
    return error instanceof ApiError && (error.status === 401 || error.status === 403 || error.status === 404)
}

function errorMessage(error: unknown): string {
    if (error instanceof ApiError) {
        return error.detail || error.message
    }
    return error instanceof Error ? error.message : 'Unknown error'
}

/** Sends one chunk, waiting out rate limits and retrying server, network and timeout errors. */
async function sendWithRetries(
    send: (signal: AbortSignal) => Promise<PushTokenImportResponseApi>,
    sleep: Sleep,
    stop: AbortSignal
): Promise<PushTokenImportResponseApi> {
    let retries = 0
    let rateLimitWaits = 0
    for (;;) {
        if (stop.aborted) {
            throw new ImportStopped()
        }
        // One controller per attempt: aborted by the stop signal or by the timeout, whichever comes first.
        const attempt = new AbortController()
        const abortAttempt = (): void => attempt.abort()
        stop.addEventListener('abort', abortAttempt)
        const timer = setTimeout(
            () => attempt.abort(new DOMException('The request took too long', 'TimeoutError')),
            REQUEST_TIMEOUT_MS
        )
        try {
            return await send(attempt.signal)
        } catch (error) {
            if (stop.aborted) {
                throw new ImportStopped()
            }
            if (error instanceof ApiError && error.status === 429 && rateLimitWaits < MAX_RATE_LIMIT_WAITS) {
                rateLimitWaits++
                await sleep(rateLimitWaitMs(error), stop)
                continue
            }
            if (isRetryable(error) && retries < RETRY_DELAYS_MS.length) {
                await sleep(RETRY_DELAYS_MS[retries++], stop)
                continue
            }
            throw error
        } finally {
            clearTimeout(timer)
            stop.removeEventListener('abort', abortAttempt)
        }
    }
}

/** Sends every row in order, one chunk at a time, and collects the rows that were not stored. */
export async function runPushTokenImport({
    rows,
    send,
    createMissingPersons = false,
    sleep,
    onChunkDone,
    stop,
}: {
    rows: PushTokenRow[]
    send: SendPushTokens
    createMissingPersons?: boolean
    sleep: Sleep
    onChunkDone: (rowsDone: number, imported: number) => void
    /** Aborted when the person stops the import or leaves the page. Cancels the request in flight too. */
    stop: AbortSignal
}): Promise<PushTokenImportOutcome> {
    const chunks = chunkRows(rows)
    const failed: FailedPushTokenRow[] = []
    let imported = 0
    let rowsDone = 0
    for (let index = 0; index < chunks.length; index++) {
        const chunk = chunks[index]
        const notSent = (reason: string): FailedPushTokenRow[] =>
            chunks.slice(index).flatMap((rest) => rest.map((row) => ({ ...row, reason })))
        const stopped = (): PushTokenImportOutcome => ({
            imported,
            failed: [...failed, ...notSent('The import was stopped, import it again')],
            stoppedReason: 'cancelled',
        })
        if (stop.aborted) {
            return stopped()
        }
        const subscriptions = chunk.map(({ distinct_id, device_token }) => ({ distinct_id, device_token }))
        try {
            const result = await sendWithRetries(
                (signal) => send(subscriptions, { create_missing_persons: createMissingPersons }, signal),
                sleep,
                stop
            )
            imported += result.imported
            failed.push(...failedRowsOf(chunk, result.failed))
        } catch (error) {
            if (error instanceof ImportStopped) {
                return stopped()
            }
            const reason = errorMessage(error)
            if (stopsImport(error)) {
                return { imported, failed: [...failed, ...notSent(`Not sent: ${reason}`)], stoppedReason: reason }
            }
            failed.push(...chunk.map((row) => ({ ...row, reason: `Not sent: ${reason}` })))
        }
        rowsDone += chunk.length
        onChunkDone(rowsDone, imported)
    }
    return { imported, failed, stoppedReason: null }
}
