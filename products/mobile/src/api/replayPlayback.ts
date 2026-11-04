import { abortError } from '@/lib/abort'

import { ApiError, apiJson, apiReadStreamResponse, projectPath } from './client'
import { type ReplayRequestState, withReplayBudget } from './replayBudget'
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

export class ReplayByteBudget {
    private encodedBytes = 0
    private decodedBytes = 0

    claimEncoded(bytes: number): void {
        this.encodedBytes += bytes
        this.check(this.encodedBytes)
    }

    claimDecoded(bytes: number): void {
        this.decodedBytes += bytes
        this.check(this.decodedBytes)
    }

    private check(bytes: number): void {
        if (bytes > MAX_PLAYER_BYTES) {
            throw new Error('This recording is too large to play on this device.')
        }
    }
}

export async function fetchReplaySources(sessionId: string, signal: AbortSignal): Promise<ReplaySources> {
    const response = await withReplayBudget(
        () =>
            apiJson<ReplaySources>(projectPath(`session_recordings/${encodeURIComponent(sessionId)}/snapshots/`), {
                signal,
                budgetFamily: 'replay',
            }),
        signal
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

async function readReplayBlock(response: Response, signal: AbortSignal, budget: ReplayByteBudget): Promise<string> {
    if (!response.ok) {
        void response.body?.cancel().catch(() => undefined)
        throw new ApiError(response.status, undefined, response.headers)
    }
    if (!response.body) {
        throw new Error("Couldn't load this recording. Try again.")
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    const parts: string[] = []
    let complete = false
    const cancel = (): void => {
        void reader.cancel().catch(() => undefined)
    }
    signal.addEventListener('abort', cancel, { once: true })
    try {
        while (true) {
            if (signal.aborted) throw abortError()
            const { value, done } = await transport(() => reader.read())
            if (signal.aborted) throw abortError()
            if (value) budget.claimEncoded(value.byteLength)
            const text = done ? decoder.decode() : decoder.decode(value, { stream: true })
            budget.claimDecoded(text.length * 2)
            parts.push(text)
            if (done) {
                complete = true
                return parts.join('')
            }
        }
    } finally {
        signal.removeEventListener('abort', cancel)
        if (!complete) cancel()
        reader.releaseLock()
    }
}

export function fetchReplayBlock(
    sessionId: string,
    source: ReplaySource,
    signal: AbortSignal,
    options: { budget: ReplayByteBudget; onRequestState?: (state: ReplayRequestState) => void }
): Promise<string> {
    return withReplayBudget(
        () =>
            apiReadStreamResponse(
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
                (response, readSignal) => readReplayBlock(response, readSignal, options.budget)
            ),
        signal,
        options.onRequestState
    )
}
