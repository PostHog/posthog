import {
    parseMarkdownNotebook,
    serializeMarkdownNotebook,
    serializeNode,
} from 'lib/components/MarkdownNotebook/markdown'
import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import { getInlineText } from 'lib/components/MarkdownNotebook/utils'
import { uuid } from 'lib/utils/dom'

import type { NotebookAppBlockApi, NotebookAppLayoutApi } from '../generated/api.schemas'

export function appCellTitle(node: NotebookBlockNode): string {
    if (node.type === 'component') {
        return String(node.props.title || node.props.name || node.tagName)
    }
    if ('children' in node) {
        return getInlineText(node.children).slice(0, 80) || 'Text'
    }
    return node.type === 'code' ? node.language || 'Code' : node.type === 'table' ? 'Table' : 'List'
}

export function appSourceCells(markdown: string): NotebookBlockNode[] {
    return parseMarkdownNotebook(markdown)
        .nodes.filter(
            (node) =>
                !(
                    node.type === 'component' &&
                    ['Comment', 'Prompt', 'NotebookComment', 'Columns', 'Column', 'ColumnEnd', 'ColumnsEnd'].includes(
                        node.tagName
                    )
                ) && !(node.type === 'paragraph' && !getInlineText(node.children).trim())
        )
        .map((node) =>
            node.type === 'component' && typeof node.props.nodeId === 'string' && node.props.nodeId
                ? { ...node, id: node.props.nodeId }
                : node
        )
}

export function emptyAppLayout(): NotebookAppLayoutApi {
    return { title: '', description: '', full_width: false, tabs: [{ id: 'overview', title: 'Overview' }], blocks: [] }
}

export function newAppBlock(
    kind: NotebookAppBlockApi['kind'],
    tabId: string,
    patch: Partial<NotebookAppBlockApi> = {}
): NotebookAppBlockApi {
    return { id: uuid(), kind, tab_id: tabId, title: '', width: kind === 'input' ? 4 : 12, ...patch }
}

export function pinAppCell(markdown: string, nodeId: string): { markdown: string; nodeId: string } {
    const pinned = pinAppCells(markdown, [nodeId])
    return { markdown: pinned.markdown, nodeId: pinned.nodeIds[0] }
}

export function pinAppCells(markdown: string, nodeIds: string[]): { markdown: string; nodeIds: string[] } {
    const document = parseMarkdownNotebook(markdown)
    const sources = new Map(
        document.nodes.flatMap((node) => [
            [node.id, node] as const,
            ...(node.type === 'component' && typeof node.props.nodeId === 'string'
                ? [[node.props.nodeId, node] as const]
                : []),
        ])
    )
    let changed = false
    const pinnedIds = nodeIds.map((nodeId) => {
        const node = sources.get(nodeId)
        if (!node || node.id.startsWith('phb-') || (node.type === 'component' && node.props.nodeId)) {
            return nodeId
        }
        // Pin against the original parse: anchoring one repeated paragraph changes the next paragraph's derived ID.
        const pinnedId = `phb-${uuid()}`
        node.id = pinnedId
        if (node.type === 'component') {
            node.props = { ...node.props, nodeId: pinnedId }
            node.raw = undefined
        }
        changed = true
        return pinnedId
    })
    return { markdown: changed ? serializeMarkdownNotebook(document) : markdown, nodeIds: pinnedIds }
}

export function normalizeAppLayout(layout: NotebookAppLayoutApi): NotebookAppLayoutApi {
    return {
        ...layout,
        blocks: layout.blocks.map((block) => ({
            ...block,
            ...(block.options ? { options: block.options.map((option) => option.trim()).filter(Boolean) } : {}),
        })),
    }
}

export function moveAppBlock(layout: NotebookAppLayoutApi, id: string, beforeId: string): NotebookAppLayoutApi {
    const block = layout.blocks.find((item) => item.id === id)
    const target = layout.blocks.find((item) => item.id === beforeId)
    if (!block || !target || id === beforeId) {
        return layout
    }
    const blocks = layout.blocks.filter((item) => item.id !== id)
    blocks.splice(
        blocks.findIndex((item) => item.id === beforeId),
        0,
        { ...block, tab_id: target.tab_id }
    )
    return { ...layout, blocks }
}

export function appCellMarkdown(node: NotebookBlockNode): string {
    if (node.type !== 'component') {
        return serializeNode(node)
    }
    return serializeNode({
        ...node,
        props: {
            ...node.props,
            ...(['SQLV2', 'PythonV2', 'Query', 'Insight', 'Widget'].includes(node.tagName)
                ? { height: node.props.height ?? 400 }
                : {}),
            hideInput: true,
            showSource: false,
            showFilters: false,
        },
    })
}

export function mergeAppCellOutput(markdown: string, nodeId: string, outputMarkdown: string): string {
    const output = appSourceCells(outputMarkdown).find((node) => node.id === nodeId)
    const document = parseMarkdownNotebook(markdown)
    const source = document.nodes.find((node) => node.type === 'component' && node.props.nodeId === nodeId)
    if (
        !source ||
        source.type !== 'component' ||
        output?.type !== 'component' ||
        source.props.code !== output.props.code
    ) {
        return markdown
    }
    const execution = Object.fromEntries(
        ['runId', 'result', 'runStatus'].filter((key) => key in output.props).map((key) => [key, output.props[key]])
    )
    if (
        Object.entries(execution).every(([key, value]) => JSON.stringify(source.props[key]) === JSON.stringify(value))
    ) {
        return markdown
    }
    source.props = { ...source.props, ...execution }
    source.raw = undefined
    return serializeMarkdownNotebook(document)
}
