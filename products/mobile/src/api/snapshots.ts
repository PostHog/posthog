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

function snapshotsPath(sessionId: string): string {
    return projectPath(`session_recordings/${encodeURIComponent(sessionId)}/snapshots/`)
}

/** The recording's blocks in time order. Only `blob_v2` blocks with both timestamps can be played in the app. */
export async function fetchSnapshotBlocks(sessionId: string, signal?: AbortSignal): Promise<SnapshotBlock[]> {
    const body = await apiJson<SnapshotSourcesApi>(snapshotsPath(sessionId), { signal, budgetFamily: 'snapshots' })
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
    return apiReadResponse(
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
    )
}
