import type { Editor, JSONContent } from '@tiptap/core'
import { Fragment, NodeType, Node as ProseMirrorNode } from '@tiptap/pm/model'
import { NodeSelection, TextSelection } from '@tiptap/pm/state'
import { findWrapping } from '@tiptap/pm/transform'

import { EmailBlockStyle, EmailPageStyle, resolvePageStyle } from './emailDocument'
import { headingSize } from './renderEmailHtml'

export interface EmailBlockAt {
    node: ProseMirrorNode
    pos: number
    /** The containing node: the document, a column or a section. */
    parent: ProseMirrorNode
    index: number
}

function isBlockContainer(node: ProseMirrorNode): boolean {
    return ['doc', 'emailColumn', 'emailSection'].includes(node.type.name)
}

/** The movable block at a document position: the deepest one directly inside the document, a column or a section. */
export function blockAtPos(doc: ProseMirrorNode, pos: number): EmailBlockAt | null {
    const $pos = doc.resolve(Math.min(Math.max(0, pos), doc.content.size))
    for (let depth = $pos.depth; depth >= 0; depth--) {
        const container = $pos.node(depth)
        if (isBlockContainer(container)) {
            const index = $pos.index(depth)
            const node = container.maybeChild(index)
            if (!node) {
                return null
            }
            return { node, pos: $pos.posAtIndex(index, depth), parent: container, index }
        }
    }
    return null
}

/** The block the style panel edits. A selected image, a list as a whole, or the block holding the cursor. */
export function selectedBlock(editor: Editor): EmailBlockAt | null {
    const { selection, doc } = editor.state
    return blockAtPos(doc, selection.from)
}

/** The columns block around the cursor, so a block inside a column can also reach its section's settings. */
export function enclosingColumns(editor: Editor): { node: ProseMirrorNode; pos: number; columnIndex: number } | null {
    const { selection } = editor.state
    if (selection instanceof NodeSelection && selection.node.type.name === 'emailColumns') {
        return { node: selection.node, pos: selection.from, columnIndex: 0 }
    }
    const { $from } = selection
    for (let depth = $from.depth; depth > 0; depth--) {
        if ($from.node(depth).type.name === 'emailColumns') {
            return { node: $from.node(depth), pos: $from.before(depth), columnIndex: $from.index(depth) }
        }
    }
    return null
}

/** The section around the cursor, so a block inside it can also reach its settings. */
export function enclosingSection(editor: Editor): { node: ProseMirrorNode; pos: number } | null {
    const { selection } = editor.state
    if (selection instanceof NodeSelection && selection.node.type.name === 'emailSection') {
        return { node: selection.node, pos: selection.from }
    }
    const { $from } = selection
    for (let depth = $from.depth; depth > 0; depth--) {
        if ($from.node(depth).type.name === 'emailSection') {
            return { node: $from.node(depth), pos: $from.before(depth) }
        }
    }
    return null
}

function withoutEmptyValues(style: EmailBlockStyle): EmailBlockStyle | null {
    const entries = Object.entries(style).filter(([, value]) => value !== undefined && value !== null && value !== '')
    return entries.length ? (Object.fromEntries(entries) as EmailBlockStyle) : null
}

export function setBlockStyle(editor: Editor, pos: number, patch: Partial<EmailBlockStyle>): void {
    const node = editor.state.doc.nodeAt(pos)
    if (!node) {
        return
    }
    const merged = withoutEmptyValues({ ...node.attrs.emailStyle, ...patch })
    editor.view.dispatch(editor.state.tr.setNodeAttribute(pos, 'emailStyle', merged))
}

export function setBlockAttribute(editor: Editor, pos: number, name: string, value: unknown): void {
    if (editor.state.doc.nodeAt(pos)) {
        editor.view.dispatch(editor.state.tr.setNodeAttribute(pos, name, value))
    }
}

function inheritedSize(doc: ProseMirrorNode, pos: number): number {
    const $pos = doc.resolve(pos)
    const page = resolvePageStyle(doc.attrs.page)
    for (let depth = $pos.depth; depth > 0; depth--) {
        const { type, attrs } = $pos.node(depth)
        if (attrs.emailStyle?.fontSize) {
            return attrs.emailStyle.fontSize
        }
        if (type.name === 'heading') {
            return headingSize(attrs.level, page)
        }
    }
    return page.fontSize
}

/** An imported line height in pixels was worked out from its text's old size, so it keeps its share of the new one. */
export function setSelectedSize(editor: Editor, fontSize: number | undefined): void {
    const { doc, selection } = editor.state
    const { from, to } = selection
    editor
        .chain()
        .setMark('textStyle', { fontSize: fontSize ?? null })
        .command(({ tr }) => {
            doc.nodesBetween(from, to, (node, pos) => {
                const mark = node.marks.find(({ type }) => type.name === 'textStyle')
                const pixels = Number(/^([\d.]+)px$/.exec(mark?.attrs.lineHeight ?? '')?.[1])
                if (mark && pixels) {
                    const oldSize = mark.attrs.fontSize ?? inheritedSize(doc, pos)
                    const lineHeight = `${Math.round((pixels / oldSize) * 100)}%`
                    tr.addMark(
                        Math.max(from, pos),
                        Math.min(to, pos + node.nodeSize),
                        mark.type.create({ ...mark.attrs, fontSize: fontSize ?? null, lineHeight })
                    )
                }
            })
            return true
        })
        .run()
}

export function setPageStyle(editor: Editor, patch: Partial<EmailPageStyle>): void {
    const page = { ...editor.state.doc.attrs.page, ...patch }
    editor.view.dispatch(editor.state.tr.setDocAttribute('page', page))
}

export function selectInserted(editor: Editor, pos: number): void {
    const { doc, tr } = editor.state
    const node = doc.nodeAt(pos)
    if (!node) {
        return
    }
    const selection =
        node.isAtom || node.type.name === 'horizontalRule'
            ? NodeSelection.create(doc, pos)
            : node.type.name === 'emailButton'
              ? // So typing replaces the placeholder label.
                TextSelection.create(doc, pos + 1, pos + 1 + node.content.size)
              : TextSelection.near(doc.resolve(pos + 1))
    editor.view.dispatch(tr.setSelection(selection).scrollIntoView())
    editor.view.focus()
}

/** The block itself, or the closest one around it that another block of this type can go next to. */
function blockThatCanPrecede(doc: ProseMirrorNode, block: EmailBlockAt | null, type: NodeType): EmailBlockAt | null {
    let candidate = block
    while (candidate && !candidate.parent.canReplaceWith(candidate.index + 1, candidate.index + 1, type)) {
        const $pos = doc.resolve(candidate.pos)
        candidate = $pos.depth > 0 ? blockAtPos(doc, $pos.before()) : null
    }
    return candidate
}

/** Puts the selected blocks in a section. False unless the selection covers several blocks that can share one. */
function wrapSelectionInSection(editor: Editor, content: JSONContent): boolean {
    const { selection, schema, tr } = editor.state
    const range = selection.$from.blockRange(selection.$to)
    const type = schema.nodes.emailSection
    const wrapping = range && range.endIndex - range.startIndex > 1 ? findWrapping(range, type, content.attrs) : null
    // A longer wrapping puts something else around the section to make it fit.
    if (!range || wrapping?.length !== 1) {
        return false
    }
    editor.view.dispatch(tr.wrap(range, wrapping).scrollIntoView())
    editor.view.focus()
    return true
}

/** Adds a block after the current one, or in place of it when that block is an empty line. */
export function insertBlock(editor: Editor, content: JSONContent): void {
    const { doc, selection } = editor.state
    if (content.type === 'emailSection' && wrapSelectionInSection(editor, content)) {
        return
    }
    const node = doc.type.schema.nodeFromJSON(content)
    const block = blockThatCanPrecede(doc, blockAtPos(doc, selection.from), node.type)
    if (!block) {
        editor.view.dispatch(editor.state.tr.insert(doc.content.size, node))
        selectInserted(editor, doc.content.size)
        return
    }
    const isEmptyLine = block.node.type.name === 'paragraph' && block.node.content.size === 0
    const canReplace = isEmptyLine && block.parent.canReplaceWith(block.index, block.index + 1, node.type)
    if (canReplace) {
        editor.view.dispatch(editor.state.tr.replaceWith(block.pos, block.pos + block.node.nodeSize, node))
        selectInserted(editor, block.pos)
        return
    }
    const insertAt = block.pos + block.node.nodeSize
    editor.view.dispatch(editor.state.tr.insert(insertAt, node))
    selectInserted(editor, insertAt)
}

export function moveBlock(editor: Editor, block: EmailBlockAt, direction: -1 | 1): boolean {
    const sibling = block.parent.maybeChild(block.index + direction)
    if (!sibling) {
        return false
    }
    const { tr } = editor.state
    const copy = block.node
    tr.delete(block.pos, block.pos + block.node.nodeSize)
    const insertAt = direction === -1 ? block.pos - sibling.nodeSize : block.pos + sibling.nodeSize
    tr.insert(insertAt, copy)
    const selection = copy.isAtom
        ? NodeSelection.create(tr.doc, insertAt)
        : TextSelection.near(tr.doc.resolve(insertAt + 1))
    editor.view.dispatch(tr.setSelection(selection).scrollIntoView())
    return true
}

export function duplicateBlock(editor: Editor, block: EmailBlockAt): void {
    const insertAt = block.pos + block.node.nodeSize
    editor.view.dispatch(editor.state.tr.insert(insertAt, block.node.copy(block.node.content)))
    selectInserted(editor, insertAt)
}

export function deleteBlock(editor: Editor, block: EmailBlockAt): void {
    const { tr } = editor.state
    if (block.parent.childCount === 1) {
        // A column or document can't be left empty, so the last block becomes an empty line.
        const paragraph = editor.state.schema.nodes.paragraph.create()
        tr.replaceWith(block.pos, block.pos + block.node.nodeSize, paragraph)
    } else {
        tr.delete(block.pos, block.pos + block.node.nodeSize)
    }
    editor.view.dispatch(tr)
    editor.view.focus()
}

function blocksInColumnsFrom(columns: ProseMirrorNode, first: number): ProseMirrorNode[] {
    const blocks: ProseMirrorNode[] = []
    for (let index = first; index < columns.childCount; index++) {
        const column = columns.child(index)
        const onlyAnEmptyLine =
            column.childCount === 1 &&
            column.firstChild?.type.name === 'paragraph' &&
            column.firstChild.content.size === 0
        if (!onlyAnEmptyLine) {
            column.forEach((block) => blocks.push(block))
        }
    }
    return blocks
}

/** Changes a columns block to a number of columns, keeping everything: blocks from removed columns join the last one. */
export function setColumnCount(editor: Editor, pos: number, count: number): void {
    const node = editor.state.doc.nodeAt(pos)
    if (!node || node.type.name !== 'emailColumns' || node.childCount === count) {
        return
    }
    const { schema, tr } = editor.state
    const columnsEnd = pos + node.nodeSize - 1
    if (node.childCount < count) {
        // Inserted at the end so the cursor stays where it is.
        for (let index = node.childCount; index < count; index++) {
            tr.insert(columnsEnd, schema.nodes.emailColumn.create(null, schema.nodes.paragraph.create()))
        }
        editor.view.dispatch(tr)
        return
    }
    let removedFrom = pos + 1
    for (let index = 0; index < count; index++) {
        removedFrom += node.child(index).nodeSize
    }
    const moved = blocksInColumnsFrom(node, count)
    tr.delete(removedFrom, columnsEnd)
    if (moved.length) {
        tr.insert(removedFrom - 1, Fragment.fromArray(moved))
    }
    editor.view.dispatch(tr)
}

export function setColumnRatios(editor: Editor, pos: number, ratios: number[]): void {
    const node = editor.state.doc.nodeAt(pos)
    if (!node || node.type.name !== 'emailColumns') {
        return
    }
    const { tr } = editor.state
    let columnPos = pos + 1
    node.forEach((column, _offset, index) => {
        tr.setNodeAttribute(columnPos, 'ratio', ratios[index] ?? 1)
        columnPos += column.nodeSize
    })
    editor.view.dispatch(tr)
}

export const EMPTY_COLUMN: JSONContent = { type: 'emailColumn', content: [{ type: 'paragraph' }] }

export const UNSUBSCRIBE_LINE: JSONContent = {
    type: 'paragraph',
    attrs: { emailStyle: { fontSize: 12, color: '#666666', textAlign: 'center' } },
    content: [
        { type: 'text', text: "Don't want to receive these emails? " },
        {
            type: 'text',
            text: 'Unsubscribe',
            marks: [{ type: 'link', attrs: { href: '{{ unsubscribe_url }}' } }],
        },
    ],
}

/** True when the html has an unsubscribe link the recipient can use, whichever way it was added. */
export function hasUnsubscribeLink(html: string): boolean {
    return /unsubscribe_url/.test(html)
}
