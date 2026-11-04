import { ApiError, apiJson, apiReadResponse, projectPath } from './client'
import { transport } from './transport'

export interface ReplaySource {
    source: 'blob_v2'
    blob_key: string
}

export interface ReplaySources {
    sources: ReplaySource[]
    replay_proxy_token?: string | null
}

export const MAX_PLAYER_BLOCKS = 60
export const MAX_PLAYER_BYTES = 24 * 1024 * 1024

export async function fetchReplaySources(sessionId: string, signal: AbortSignal): Promise<ReplaySources> {
    const response = await apiJson<ReplaySources>(
        projectPath(`session_recordings/${encodeURIComponent(sessionId)}/snapshots/`),
        { signal, budgetFamily: 'replay' }
    )
    if (!Array.isArray(response.sources) || response.sources.length === 0) {
        throw new Error('This recording has no playback data yet. Try again in a moment.')
    }
    if (response.sources.length > MAX_PLAYER_BLOCKS) {
        throw new Error('This recording is too large to play on this device.')
    }
    if (response.sources.some((source) => source.source !== 'blob_v2' || !/^\d+$/.test(source.blob_key))) {
        throw new Error("This recording's format isn't supported yet.")
    }
    return response
}

export async function fetchReplayBlock(sessionId: string, source: ReplaySource, signal: AbortSignal): Promise<string> {
    return apiReadResponse(
        projectPath(`session_recordings/${encodeURIComponent(sessionId)}/snapshots/`),
        {
            signal,
            budgetFamily: 'replay',
            query: {
                source: source.source,
                start_blob_key: source.blob_key,
                end_blob_key: source.blob_key,
                decompress: true,
            },
        },
        async (response) => {
            if (!response.ok) {
                throw new ApiError(response.status, undefined, response.headers)
            }
            const text = await transport(() => response.text())
            if (text.length * 2 > MAX_PLAYER_BYTES) {
                throw new Error('This recording is too large to play on this device.')
            }
            return text
        }
    )
}
