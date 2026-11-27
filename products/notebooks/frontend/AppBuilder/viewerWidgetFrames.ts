import type { WidgetFrameApi } from '../generated/api.schemas'
import type { WidgetFrameSession } from '../NotebookNodeGeneratedWidget/widgetFrameSession'
import type { ViewerOutput } from './notebookAppViewerLogic'

export function viewerWidgetSession(
    outputs: Record<string, ViewerOutput>,
    widgetId: string,
    versionId: string | null
): WidgetFrameSession {
    const frames = viewerWidgetFrames(outputs, widgetId, versionId)
    return {
        revision: JSON.stringify(
            Array.from(frames, ([name, { sourceNodeId, runId, output }]) => [
                name,
                sourceNodeId,
                runId,
                output.generation,
            ])
        ),
        read: async (slot, offset, limit, load) => {
            const viewer = frames.get(slot)
            if (!viewer) {
                return await load(offset, limit)
            }
            const frame = await load(0, 0, viewer.runId)
            if (frame.runId !== viewer.runId) {
                throw new Error('The widget source run changed. Refresh the app to load the new binding.')
            }
            return viewerWidgetPage(frame, viewer.sourceNodeId, viewer.output, offset, limit)
        },
    }
}

export function viewerWidgetFrames(
    outputs: Record<string, ViewerOutput>,
    widgetId: string,
    versionId: string | null | undefined
): Map<string, { sourceNodeId: string; runId: string; output: ViewerOutput }> {
    const frames = new Map<string, { sourceNodeId: string; runId: string; output: ViewerOutput }>()
    for (const [sourceNodeId, output] of Object.entries(outputs)) {
        for (const binding of output.widgetSlots) {
            if (binding.node_id === widgetId && binding.version_id === versionId && binding.run_id) {
                frames.set(binding.slot, { sourceNodeId, runId: binding.run_id, output })
            }
        }
    }
    return frames
}

export function viewerWidgetPage(
    frame: WidgetFrameApi,
    sourceNodeId: string,
    { result }: ViewerOutput,
    offset: number,
    limit: number
): WidgetFrameApi {
    if (frame.sourceNodeId !== sourceNodeId) {
        throw new Error('The widget input changed. Refresh the app to load the new binding.')
    }
    validateWidgetColumns(frame.columns, result)
    if (offset >= 5000) {
        throw new Error('Widget data is limited to 5,000 rows per dataframe.')
    }
    const encoder = new TextEncoder()
    let bytes = encoder.encode(JSON.stringify({ name: frame.name, columns: frame.columns })).byteLength
    const rows: unknown[][] = []
    for (const values of result.results.slice(offset, Math.min(offset + limit, 5000))) {
        if (!Array.isArray(values) || values.length !== frame.columns.length) {
            throw new Error('The filtered rows do not match the widget columns.')
        }
        const row = values.map((value: unknown) => {
            if (value === null || typeof value === 'number' || typeof value === 'boolean') {
                return value
            }
            return (typeof value === 'string' ? value : (JSON.stringify(value) ?? '')).slice(0, 4096)
        })
        bytes += encoder.encode(JSON.stringify(row)).byteLength
        if (bytes > 512 * 1024) {
            if (!rows.length) {
                throw new Error('A filtered row is too large for the widget.')
            }
            break
        }
        rows.push(row)
    }
    const end = offset + rows.length
    return {
        name: frame.name,
        runId: frame.runId,
        columns: frame.columns,
        rows,
        offset,
        includedRowCount: rows.length,
        totalRowCount: result.results.length,
        nextOffset: end < Math.min(result.results.length, 5000) ? end : null,
        truncated: end < result.results.length || !!result.hasMore,
    }
}

function validateWidgetColumns(columns: WidgetFrameApi['columns'], result: ViewerOutput['result']): void {
    if (
        result.columns?.length !== columns.length ||
        columns.some(
            ({ name, type }, index) =>
                name !== result.columns?.[index] || (type !== 'unknown' && type !== result.types?.[index]?.[1])
        )
    ) {
        throw new Error('The filtered columns changed. Update the widget input to use this result.')
    }
}

export function parseWidgetQueryResponse(text: string): unknown {
    if (!/\d{16}/.test(text)) {
        return JSON.parse(text)
    }
    // Consume quoted JSON strings whole so digits inside strings and object keys stay untouched.
    const tokens = /"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g
    const exact = text.replace(tokens, (token) =>
        token[0] !== '"' && /^-?\d{16,}$/.test(token) && !Number.isSafeInteger(Number(token))
            ? '"' + token + '"'
            : token
    )
    return JSON.parse(exact)
}
