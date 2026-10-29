import Papa from 'papaparse'

import { ApiError } from 'lib/api'

import type {
    PushTokenImportResponseApi,
    PushTokenSubscriptionApi,
} from 'products/integrations/frontend/generated/api.schemas'

// Limits of the import endpoint. A request over them is refused as a whole.
export const ROWS_PER_REQUEST = 1000
const MAX_DISTINCT_ID_LENGTH = 200
const MAX_DEVICE_TOKEN_LENGTH = 4096

const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000]
const MAX_RATE_LIMIT_WAITS = 10
const DEFAULT_RATE_LIMIT_WAIT_MS = 10_000
const MAX_RATE_LIMIT_WAIT_MS = 60_000

export interface PushTokenRow extends PushTokenSubscriptionApi {
    /** Line in the uploaded file, counting the header as line 1. */
    line: number
}

export interface RejectedPushTokenRow {
    line: number
    distinct_id: string
    device_token: string
    reason: string
}

export interface ParsedPushTokenCsv {
    rows: PushTokenRow[]
    rejected: RejectedPushTokenRow[]
    duplicates: number
}

export interface PushTokenImportOutcome {
    imported: number
    failed: RejectedPushTokenRow[]
    /** Set when the import stopped before sending every row. */
    stoppedReason: string | null
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
    const rejected: RejectedPushTokenRow[] = []
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

export function chunkRows(rows: PushTokenRow[]): PushTokenRow[][] {
    const chunks: PushTokenRow[][] = []
    for (let start = 0; start < rows.length; start += ROWS_PER_REQUEST) {
        chunks.push(rows.slice(start, start + ROWS_PER_REQUEST))
    }
    return chunks
}

function rateLimitWaitMs(error: ApiError): number {
    const retryAfter = Number(error.headers?.get('Retry-After'))
    if (Number.isFinite(retryAfter) && retryAfter > 0) {
        return Math.min(retryAfter * 1000, MAX_RATE_LIMIT_WAIT_MS)
    }
    return DEFAULT_RATE_LIMIT_WAIT_MS
}

function isRetryable(error: unknown): boolean {
    if (!(error instanceof ApiError)) {
        return false
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

/** Sends one chunk, waiting out rate limits and retrying server and network errors. */
async function sendChunk(
    chunk: PushTokenRow[],
    send: (subscriptions: PushTokenSubscriptionApi[]) => Promise<PushTokenImportResponseApi>,
    sleep: (ms: number) => Promise<void>
): Promise<PushTokenImportResponseApi> {
    const subscriptions = chunk.map(({ distinct_id, device_token }) => ({ distinct_id, device_token }))
    let retries = 0
    let rateLimitWaits = 0
    for (;;) {
        try {
            return await send(subscriptions)
        } catch (error) {
            if (error instanceof ApiError && error.status === 429 && rateLimitWaits < MAX_RATE_LIMIT_WAITS) {
                rateLimitWaits++
                await sleep(rateLimitWaitMs(error))
                continue
            }
            if (isRetryable(error) && retries < RETRY_DELAYS_MS.length) {
                await sleep(RETRY_DELAYS_MS[retries++])
                continue
            }
            throw error
        }
    }
}

/** Sends every row in order, one chunk at a time, and collects the rows that were not stored. */
export async function runPushTokenImport({
    rows,
    send,
    sleep,
    onChunkDone,
    isCancelled,
}: {
    rows: PushTokenRow[]
    send: (subscriptions: PushTokenSubscriptionApi[]) => Promise<PushTokenImportResponseApi>
    sleep: (ms: number) => Promise<void>
    onChunkDone: (rowsDone: number, imported: number) => void
    isCancelled: () => boolean
}): Promise<PushTokenImportOutcome> {
    const chunks = chunkRows(rows)
    const failed: RejectedPushTokenRow[] = []
    let imported = 0
    let rowsDone = 0
    for (let index = 0; index < chunks.length; index++) {
        const chunk = chunks[index]
        const notSent = (reason: string): RejectedPushTokenRow[] =>
            chunks.slice(index).flatMap((rest) => rest.map((row) => ({ ...row, reason })))
        if (isCancelled()) {
            return {
                imported,
                failed: [...failed, ...notSent('Not sent, the import was stopped')],
                stoppedReason: 'cancelled',
            }
        }
        try {
            const result = await sendChunk(chunk, send, sleep)
            imported += result.imported
            const failedIds = new Set(result.failed_distinct_ids)
            for (const row of chunk) {
                if (failedIds.has(row.distinct_id)) {
                    failed.push({ ...row, reason: 'Not stored, import it again' })
                }
            }
        } catch (error) {
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

export function failedRowsCsv(rows: RejectedPushTokenRow[]): string {
    return Papa.unparse({
        fields: ['line', 'distinct_id', 'device_token', 'reason'],
        data: [...rows]
            .sort((a, b) => a.line - b.line)
            .map((row) => [row.line, row.distinct_id, row.device_token, row.reason]),
    })
}
