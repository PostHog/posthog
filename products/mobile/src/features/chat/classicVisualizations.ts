import { asRecord, isRecord } from '@/lib/records'
import type { SessionThreadItem } from './session/types'
import { visualizationQuery, visualizationUrl } from './visualizationModel'

function visualizationItem(
    data: Record<string, unknown>,
    id: string,
    projectUrl: string,
    feedback: { traceId?: string }
): SessionThreadItem[] {
    const content = asRecord(data.content) ?? data
    const shortId = data.short_id ?? (data.source === 'insight' ? data.artifact_id : content.short_id)
    const savedId = typeof shortId === 'string' && shortId.trim() ? shortId : undefined
    const source = data.answer ?? content.query
    const query = isRecord(source) ? visualizationQuery(source) : undefined
    if (!savedId && !query) {
        return [{ kind: 'assistant', id, text: 'Chart unavailable.', complete: true, projectUrl, ...feedback }]
    }
    const name = content.name ?? data.name ?? content.title ?? (typeof data.query === 'string' ? data.query : undefined)
    const result = data.results ?? data.result ?? content.results ?? content.result
    const resultMetadata = Array.isArray(data.columns) ? data : content
    return [
        {
            kind: 'visualization',
            id,
            query,
            shortId: savedId,
            title: typeof name === 'string' && name.trim() ? name : undefined,
            result:
                Array.isArray(result) && Array.isArray(resultMetadata.columns)
                    ? {
                          results: result,
                          columns: resultMetadata.columns,
                          types: resultMetadata.types,
                          hasMore: resultMetadata.hasMore,
                      }
                    : result,
            webUrl: visualizationUrl(query, projectUrl, savedId),
            ...feedback,
        },
    ]
}

function convertVisualizations(
    data: Record<string, unknown>,
    id: string,
    projectUrl: string,
    feedback: { traceId?: string } = {}
): SessionThreadItem[] {
    if (data.type === 'ai/multi_viz') {
        const charts = Array.isArray(data.visualizations)
            ? data.visualizations.flatMap((value, index) =>
                  visualizationItem(asRecord(value) ?? {}, `${id}-${index}`, projectUrl, feedback)
              )
            : []
        return typeof data.commentary === 'string' && data.commentary.trim()
            ? [
                  {
                      kind: 'assistant',
                      id: `${id}-commentary`,
                      text: data.commentary,
                      complete: true,
                      projectUrl,
                      ...feedback,
                  },
                  ...charts,
              ]
            : charts
    }
    const content = asRecord(data.content)
    if (content?.content_type !== 'notebook') return visualizationItem(data, id, projectUrl, feedback)
    const blocks = Array.isArray(content.blocks) ? content.blocks : []
    const items = blocks.flatMap((value, index): SessionThreadItem[] => {
        const block = asRecord(value) ?? {}
        const blockId = `${id}-block-${index}`
        if (block.type === 'visualization') return visualizationItem(block, blockId, projectUrl, feedback)
        const text =
            block.type === 'markdown' && typeof block.content === 'string'
                ? block.content
                : block.type === 'error' && typeof block.message === 'string'
                  ? block.message
                  : 'Open this report on the web to view this content.'
        return text ? [{ kind: 'assistant', id: blockId, text, complete: true, projectUrl, ...feedback }] : []
    })
    if (content.is_saved === true && typeof data.artifact_id === 'string') {
        items.push({
            kind: 'assistant',
            id: `${id}-link`,
            text: `[View notebook](${projectUrl}/notebooks/${encodeURIComponent(data.artifact_id)})`,
            complete: true,
            projectUrl,
            ...feedback,
        })
    }
    const last = items.at(-1)
    if (last?.kind === 'assistant' || last?.kind === 'visualization') {
        last.copyText = items
            .map((item) =>
                item.kind === 'assistant'
                    ? item.text
                    : item.kind === 'visualization' && item.webUrl
                      ? `[View ${item.shortId ? 'insight' : 'chart'}](${item.webUrl})`
                      : ''
            )
            .filter(Boolean)
            .join('\n\n')
    }
    return items.length
        ? items
        : [{ kind: 'assistant', id, text: 'This report has no content yet.', complete: true, projectUrl, ...feedback }]
}

interface CachedVisualizations {
    id: string
    projectUrl: string
    traceId?: string
    items: SessionThreadItem[]
}

const convertedMessages = new WeakMap<Record<string, unknown>, CachedVisualizations>()

export function classicVisualizationItems(
    data: Record<string, unknown>,
    id: string,
    projectUrl: string,
    feedback: { traceId?: string } = {}
): SessionThreadItem[] {
    const previous = convertedMessages.get(data)
    if (previous?.id === id && previous.projectUrl === projectUrl && previous.traceId === feedback.traceId)
        return previous.items
    const items = convertVisualizations(data, id, projectUrl, feedback)
    convertedMessages.set(data, { id, projectUrl, traceId: feedback.traceId, items })
    return items
}
