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
    const document = parseMarkdownNotebook(markdown)
    const node = document.nodes.find(
        (item) => item.id === nodeId || (item.type === 'component' && item.props.nodeId === nodeId)
    )
    if (!node || node.id.startsWith('phb-') || (node.type === 'component' && node.props.nodeId)) {
        return { markdown, nodeId }
    }
    // Derived text IDs change with edits. Persist an anchor before a layout starts referring to the cell.
    const pinnedId = `phb-${uuid()}`
    node.id = pinnedId
    if (node.type === 'component') {
        node.props = { ...node.props, nodeId: pinnedId }
    }
    return { markdown: serializeMarkdownNotebook(document), nodeId: pinnedId }
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
