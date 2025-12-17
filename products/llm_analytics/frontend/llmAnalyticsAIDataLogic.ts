import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { llmAnalyticsAIDataLogicType } from './llmAnalyticsAIDataLogicType'

export interface AIData {
    input: unknown
    output: unknown
}

export interface LoadAIDataParams {
    eventId: string
    input: unknown
    output: unknown
}

// Keys used to identify blob references from the backend
const AI_BLOB_URL_KEY = '$ai_blob_url'
const AI_BLOB_RANGE_KEY = '$ai_blob_range'

interface BlobReference {
    [AI_BLOB_URL_KEY]: string
    [AI_BLOB_RANGE_KEY]: string
}

function isBlobReference(value: unknown): value is BlobReference {
    return (
        typeof value === 'object' &&
        value !== null &&
        AI_BLOB_URL_KEY in value &&
        AI_BLOB_RANGE_KEY in value &&
        typeof (value as BlobReference)[AI_BLOB_URL_KEY] === 'string' &&
        typeof (value as BlobReference)[AI_BLOB_RANGE_KEY] === 'string'
    )
}

function findCRLFCRLF(bytes: Uint8Array): number {
    for (let i = 0; i < bytes.length - 3; i++) {
        if (bytes[i] === 0x0d && bytes[i + 1] === 0x0a && bytes[i + 2] === 0x0d && bytes[i + 3] === 0x0a) {
            return i
        }
    }
    return -1
}

function parseMimeHeaders(headerText: string): Record<string, string> {
    const headers: Record<string, string> = {}
    for (const line of headerText.split('\r\n')) {
        const colonIdx = line.indexOf(':')
        if (colonIdx > 0) {
            headers[line.slice(0, colonIdx).trim().toLowerCase()] = line.slice(colonIdx + 1).trim()
        }
    }
    return headers
}

async function decompressGzip(data: Uint8Array): Promise<Uint8Array> {
    const ds = new DecompressionStream('gzip')
    const decompressed = new Response(new Blob([data]).stream().pipeThrough(ds))
    return new Uint8Array(await decompressed.arrayBuffer())
}

async function parseMimePart(partBytes: Uint8Array): Promise<unknown> {
    // The byte range gives us a MIME part: headers + \r\n\r\n + body
    // The range excludes trailing \r\n (handled by capture service)
    const separatorIdx = findCRLFCRLF(partBytes)
    if (separatorIdx === -1) {
        throw new Error('Invalid MIME part: no header separator found')
    }

    const headerBytes = partBytes.slice(0, separatorIdx)
    const headerText = new TextDecoder().decode(headerBytes)
    const headers = parseMimeHeaders(headerText)

    // Body starts after \r\n\r\n (4 bytes) and goes to end (no trailing \r\n to strip)
    const bodyBytes = partBytes.slice(separatorIdx + 4)

    let body = bodyBytes
    if (headers['content-encoding'] === 'gzip') {
        body = await decompressGzip(bodyBytes)
    }

    const text = new TextDecoder().decode(body)
    return JSON.parse(text)
}

async function loadAIDataAsync(params: LoadAIDataParams): Promise<AIData> {
    const { input, output } = params

    if (!isBlobReference(input) && !isBlobReference(output)) {
        return { input, output }
    }

    // Collect blob references, grouped by URL to avoid duplicate fetches
    // (input and output are typically stored in the same S3 file)
    interface BlobInfo {
        range: string
        field: 'input' | 'output'
    }
    const urlToBlobs = new Map<string, BlobInfo[]>()

    const collectBlob = (field: 'input' | 'output', value: unknown): void => {
        if (isBlobReference(value)) {
            const url = value[AI_BLOB_URL_KEY]
            const range = value[AI_BLOB_RANGE_KEY]
            if (!urlToBlobs.has(url)) {
                urlToBlobs.set(url, [])
            }
            urlToBlobs.get(url)!.push({ range, field })
        }
    }

    collectBlob('input', input)
    collectBlob('output', output)

    // Start with non-blob values
    const resolved: { input: unknown; output: unknown } = {
        input: isBlobReference(input) ? undefined : input,
        output: isBlobReference(output) ? undefined : output,
    }

    // Fetch each unique URL once and extract all referenced parts
    for (const [url, blobs] of urlToBlobs) {
        const response = await fetch(url) // Fetch full file, no Range header
        if (!response.ok) {
            throw new Error(`Failed to fetch blob file: ${response.status} ${response.statusText}`)
        }

        const fileBytes = new Uint8Array(await response.arrayBuffer())

        for (const { range, field } of blobs) {
            const [start, end] = range.split('-').map(Number)

            // Range is inclusive, so we need end + 1 for slice
            const partBytes = fileBytes.slice(start, end + 1)

            resolved[field] = await parseMimePart(partBytes)
        }
    }

    return resolved
}

export const llmAnalyticsAIDataLogic = kea<llmAnalyticsAIDataLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmAnalyticsAIDataLogic']),

    actions({
        loadAIDataForEvent: (params: LoadAIDataParams) => params,
        clearAIDataForEvent: (eventId: string) => ({ eventId }),
        clearAllAIData: true,
    }),

    reducers({
        aiDataCache: [
            {} as Record<string, AIData>,
            {
                loadAIDataForEventSuccess: (state, { aiDataForEvent }) => ({
                    ...state,
                    [aiDataForEvent.eventId]: {
                        input: aiDataForEvent.input,
                        output: aiDataForEvent.output,
                    },
                }),
                clearAIDataForEvent: (state, { eventId }) => {
                    const { [eventId]: _, ...rest } = state
                    return rest
                },
                clearAllAIData: () => ({}),
            },
        ],
        loadingEventIds: [
            new Set<string>(),
            {
                loadAIDataForEvent: (state, params) => {
                    const newSet = new Set(state)
                    newSet.add(params.eventId)
                    return newSet
                },
                loadAIDataForEventSuccess: (state, { aiDataForEvent }) => {
                    const newSet = new Set(state)
                    newSet.delete(aiDataForEvent.eventId)
                    return newSet
                },
                loadAIDataForEventFailure: (state, params) => {
                    const newSet = new Set(state)
                    const { eventId } = params.errorObject
                    newSet.delete(eventId)
                    return newSet
                },
            },
        ],
    }),

    selectors({
        isEventLoading: [
            (s) => [s.loadingEventIds],
            (loadingEventIds): ((eventId: string) => boolean) => {
                return (eventId: string) => loadingEventIds.has(eventId)
            },
        ],
    }),

    loaders(() => ({
        aiDataForEvent: [
            null as (AIData & { eventId: string }) | null,
            {
                loadAIDataForEvent: async (params: LoadAIDataParams) => {
                    const data = await loadAIDataAsync(params)
                    return {
                        ...data,
                        eventId: params.eventId,
                    }
                },
            },
        ],
    })),
])
