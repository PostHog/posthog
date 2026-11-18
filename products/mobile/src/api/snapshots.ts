import { abortError } from '@/lib/abort'

import { BudgetExceededError, budgetRetryAfterMs } from './budget'
import { ApiError, apiJson, apiReadResponse, projectPath } from './client'

/** One stored block of a recording, as `GET session_recordings/{id}/snapshots/` lists it. */
export interface SnapshotSourceApi {
    source: string
    start_timestamp: string | null
    end_timestamp: string | null
    blob_key: string | null
}

export interface SnapshotSourcesApi {
    sources?: SnapshotSourceApi[]
}

export interface SnapshotBlock {
    index: number
    startTs: number
    endTs: number
}

function wait(ms: number, signal: AbortSignal | undefined): Promise<void> {
    return new Promise((resolve, reject) => {
        const onAbort = (): void => {
            clearTimeout(timer)
            reject(abortError())
        }
        const timer = setTimeout(() => {
            signal?.removeEventListener('abort', onAbort)
            resolve()
        }, ms)
        signal?.addEventListener('abort', onAbort, { once: true })
        if (signal?.aborted) {
            onAbort()
        }
    })
}

/** A feed swiped fast spends the snapshot budget before the server's own limit; the player then waits, not fails. */
async function withSnapshotBudget<T>(work: () => Promise<T>, signal: AbortSignal | undefined): Promise<T> {
    while (true) {
        try {
            return await work()
        } catch (error) {
            if (!(error instanceof BudgetExceededError) || error.family !== 'snapshots') {
                throw error
            }
            await wait(Math.max(250, budgetRetryAfterMs('snapshots')), signal)
        }
    }
}

function snapshotsPath(sessionId: string): string {
    return projectPath(`session_recordings/${encodeURIComponent(sessionId)}/snapshots/`)
}

/** The recording's blocks in time order. Only `blob_v2` blocks with both timestamps can be played in the app. */
export async function fetchSnapshotBlocks(sessionId: string, signal?: AbortSignal): Promise<SnapshotBlock[]> {
    const body = await withSnapshotBudget(
        () => apiJson<SnapshotSourcesApi>(snapshotsPath(sessionId), { signal, budgetFamily: 'snapshots' }),
        signal
    )
    const blocks: SnapshotBlock[] = []
    for (const source of body.sources ?? []) {
        const index = Number(source.blob_key)
        const startTs = source.start_timestamp ? Date.parse(source.start_timestamp) : Number.NaN
        const endTs = source.end_timestamp ? Date.parse(source.end_timestamp) : Number.NaN
        if (source.source !== 'blob_v2' || !Number.isInteger(index) || Number.isNaN(startTs) || Number.isNaN(endTs)) {
            throw new Error("This recording's format isn't supported in the app yet.")
        }
        blocks.push({ index, startTs, endTs })
    }
    return blocks.sort((a, b) => a.index - b.index)
}

/**
 * The JSONL text of blocks `from` to `to`, decompressed by the server. The endpoint accepts at most 101 blocks per
 * request (`end_blob_key - start_blob_key <= 100`) for a browser session or an OAuth token.
 */
export async function fetchSnapshotRange(
    sessionId: string,
    from: number,
    to: number,
    signal?: AbortSignal
): Promise<string> {
    return withSnapshotBudget(
        () =>
            apiReadResponse(
                snapshotsPath(sessionId),
                {
                    signal,
                    budgetFamily: 'snapshots',
                    query: { source: 'blob_v2', start_blob_key: from, end_blob_key: to },
                },
                async (response) => {
                    const text = await response.text()
                    if (!response.ok) {
                        throw new ApiError(response.status, text, response.headers)
                    }
                    return text
                }
            ),
        signal
    )
}
