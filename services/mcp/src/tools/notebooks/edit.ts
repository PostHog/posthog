import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { PostHogApiError } from '@/lib/errors'
import { buildMCPAnalyticsGroups } from '@/lib/posthog/analytics'
import { isFeatureFlagEnabled } from '@/lib/posthog/flags'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const ProseMirrorNodeSchema = z
    .object({
        type: z.string().min(1).describe('The ProseMirror node type, for example paragraph, heading, or ph-query.'),
    })
    .catchall(z.unknown())

const NodesSchema = z
    .array(ProseMirrorNodeSchema)
    .min(1)
    .describe('Advanced escape hatch: one or more raw ProseMirror JSON nodes to insert.')

const ContentFormatSchema = z
    .enum(['markdown', 'plain_text'])
    .optional()
    .describe(
        'How to turn content into notebook blocks. Defaults to markdown. Markdown supports headings, lists, fenced code blocks, and <query> blocks for old-style query nodes. Use plain_text for one paragraph per non-empty line.'
    )

const InsertContentFields = {
    content: z
        .string()
        .min(1)
        .optional()
        .describe(
            'Preferred input for agents: the text or simple Markdown to insert. Provide either content or nodes, not both.'
        ),
    content_format: ContentFormatSchema,
    nodes: NodesSchema.optional(),
}

const AppendEditSchema = z
    .object({
        type: z.literal('append'),
        ...InsertContentFields,
    })
    .describe('Append content to the end of the notebook.')

const InsertAfterHeadingEditSchema = z
    .object({
        type: z.literal('insert_after_heading'),
        heading: z.string().min(1).describe('Exact plain-text heading to insert after.'),
        ...InsertContentFields,
        occurrence: z
            .number()
            .int()
            .min(1)
            .default(1)
            .describe('Which matching heading to use when the same heading appears more than once.'),
    })
    .describe('Insert content after a top-level heading with exact matching text.')

const InsertAfterEditSchema = z
    .object({
        type: z.literal('insert_after'),
        anchor: z
            .string()
            .min(1)
            .describe('Exact plain-text anchor. The new content is inserted after the top-level block containing it.'),
        ...InsertContentFields,
        occurrence: z
            .number()
            .int()
            .min(1)
            .default(1)
            .describe('Which matching anchor to use when the same text appears more than once.'),
    })
    .describe('Insert content after a top-level notebook block identified by exact text.')

const InsertBeforeEditSchema = z
    .object({
        type: z.literal('insert_before'),
        anchor: z
            .string()
            .min(1)
            .describe('Exact plain-text anchor. The new content is inserted before the top-level block containing it.'),
        ...InsertContentFields,
        occurrence: z
            .number()
            .int()
            .min(1)
            .default(1)
            .describe('Which matching anchor to use when the same text appears more than once.'),
    })
    .describe('Insert content before a top-level notebook block identified by exact text.')

const InsertBetweenEditSchema = z
    .object({
        type: z.literal('insert_between'),
        after: z
            .string()
            .min(1)
            .describe('Exact plain-text anchor. The new nodes are inserted after the top-level block containing it.'),
        before: z.string().min(1).describe('Exact plain-text anchor that must appear in a later top-level block.'),
        ...InsertContentFields,
        after_occurrence: z
            .number()
            .int()
            .min(1)
            .default(1)
            .describe('Which matching after anchor to use when the same text appears more than once.'),
        before_occurrence: z
            .number()
            .int()
            .min(1)
            .default(1)
            .describe('Which matching before anchor to use after the selected after anchor.'),
    })
    .describe('Insert content between two top-level notebook blocks identified by exact text anchors.')

const ReplaceBlockEditSchema = z
    .object({
        type: z.literal('replace_block'),
        anchor: z.string().min(1).describe('Exact plain-text anchor. Replaces the top-level block containing it.'),
        ...InsertContentFields,
        occurrence: z
            .number()
            .int()
            .min(1)
            .default(1)
            .describe('Which matching anchor to use when the same text appears more than once.'),
    })
    .describe('Replace a whole top-level notebook block identified by exact text.')

const ReplaceTextEditSchema = z
    .object({
        type: z.literal('replace_text'),
        find: z.string().min(1).describe('Exact text to find inside a single text node.'),
        replace: z.string().describe('Replacement text. Use an empty string to delete the matching text.'),
        all_occurrences: z.boolean().default(false).describe('Replace every exact match instead of only the first.'),
    })
    .describe('Replace exact plain text in notebook text nodes.')

const NotebookEditSchema = z.object({
    short_id: z.string().describe('Short ID of the notebook to edit.'),
    edits: z
        .array(
            z.discriminatedUnion('type', [
                AppendEditSchema,
                InsertAfterHeadingEditSchema,
                InsertAfterEditSchema,
                InsertBeforeEditSchema,
                InsertBetweenEditSchema,
                ReplaceBlockEditSchema,
                ReplaceTextEditSchema,
            ])
        )
        .min(1)
        .describe('Ordered notebook edits to apply. Edits are recomputed against the latest notebook on conflicts.'),
    title: z.string().optional().describe('Optional title update to save with the notebook edit.'),
    max_retries: z
        .number()
        .int()
        .min(0)
        .max(5)
        .default(3)
        .describe('How many times to reload and retry if another collaborator edits first.'),
})

type Params = z.infer<typeof NotebookEditSchema>
type NotebookEdit = Params['edits'][number]
export type ProseMirrorNode = z.infer<typeof ProseMirrorNodeSchema> & {
    content?: ProseMirrorNode[]
    marks?: unknown[]
    text?: string
}
export type ProseMirrorDoc = Record<string, unknown> & { type: 'doc'; content: ProseMirrorNode[] }
type ReplaceStep = {
    stepType: 'replace'
    from: number
    to: number
    slice?: { content: ProseMirrorNode[] }
}
type EditPlan = {
    content: ProseMirrorDoc
    steps: ReplaceStep[]
    textContent: string
}
type TextMatch = {
    from: number
    to: number
    node: ProseMirrorNode
    parent: ProseMirrorNode | ProseMirrorDoc | null
    childIndex: number | null
    startIndex: number
}
type NotebookEditResult = Schemas.Notebook & { applied_edits: number }

const MAX_TEXT_REPLACEMENTS = 100
const LEAF_NODE_TYPES = new Set(['hardBreak', 'horizontalRule'])
const NOTEBOOK_PYTHON_FEATURE_FLAG = 'notebook-python'
const ANALYSIS_BLOCK_PATTERN = /^[ \t]*<(python|hogql|ducksql|duckdb|query)\b([^>]*)>\n?([\s\S]*?)\n?<\/\1>[ \t]*$/gim
const EXECUTABLE_ANALYSIS_BLOCK_PATTERN =
    /^[ \t]*<(python|hogql|ducksql|duckdb)\b([^>]*)>\n?([\s\S]*?)\n?<\/\1>[ \t]*$/gim
const ATTRIBUTE_PATTERN = /([A-Za-z_][\w:-]*)\s*=\s*("[^"]*"|'[^']*'|[^\s"'>]+)/g
const EXECUTABLE_ANALYSIS_NODE_TYPES = new Set(['ph-python', 'ph-hogql-sql', 'ph-duck-sql'])

function cloneJson<T>(value: T): T {
    return JSON.parse(JSON.stringify(value)) as T
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function normalizeDocument(content: unknown): ProseMirrorDoc {
    if (!isRecord(content)) {
        return { type: 'doc', content: [] }
    }

    const cloned = cloneJson(content)
    const rawContent = Array.isArray(cloned.content) ? cloned.content : []

    return {
        ...cloned,
        type: 'doc',
        content: rawContent.filter(isRecord) as ProseMirrorNode[],
    }
}

function nodeSize(node: ProseMirrorNode): number {
    if (node.type === 'text') {
        return typeof node.text === 'string' ? node.text.length : 0
    }

    if (!Array.isArray(node.content)) {
        return node.type.startsWith('ph-') || LEAF_NODE_TYPES.has(node.type) ? 1 : 2
    }

    return 2 + node.content.reduce((size, child) => size + nodeSize(child), 0)
}

function documentContentSize(doc: ProseMirrorDoc): number {
    return doc.content.reduce((size, child) => size + nodeSize(child), 0)
}

function replaceStep(from: number, to: number, content: ProseMirrorNode[] = []): ReplaceStep {
    const step: ReplaceStep = { stepType: 'replace', from, to }
    if (content.length > 0) {
        step.slice = { content: cloneJson(content) }
    }
    return step
}

function textContent(node: ProseMirrorNode | ProseMirrorDoc): string {
    if (node.type === 'text') {
        return typeof node.text === 'string' ? node.text : ''
    }

    const attrs = isRecord(node.attrs) ? node.attrs : {}
    if (node.type === 'ph-python') {
        return codeNodeText('python', attrs)
    }
    if (node.type === 'ph-hogql-sql') {
        return codeNodeText('hogql', attrs)
    }
    if (node.type === 'ph-duck-sql') {
        return codeNodeText('ducksql', attrs)
    }
    if (node.type === 'ph-query') {
        return queryNodeText(attrs)
    }
    if (node.type === 'ph-recording') {
        return typeof attrs.id === 'string' ? `<session_replay id="${escapeAttribute(attrs.id)}" />` : ''
    }

    if (!Array.isArray(node.content)) {
        return ''
    }

    const childText = node.content.map(textContent).filter((text) => text.length > 0)
    if (node.type === 'bulletList' || node.type === 'orderedList' || node.type === 'listItem') {
        return childText.join('\n')
    }
    return childText.join('')
}

function escapeAttribute(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function codeNodeText(tag: 'python' | 'hogql' | 'ducksql', attrs: Record<string, unknown>): string {
    const attrParts: string[] = []
    if (typeof attrs.title === 'string' && attrs.title.length > 0) {
        attrParts.push(`title="${escapeAttribute(attrs.title)}"`)
    }
    if (tag !== 'python' && typeof attrs.returnVariable === 'string' && attrs.returnVariable.length > 0) {
        attrParts.push(`return_variable="${escapeAttribute(attrs.returnVariable)}"`)
    }

    const code = typeof attrs.code === 'string' ? attrs.code : ''
    const attrText = attrParts.length > 0 ? ` ${attrParts.join(' ')}` : ''
    return `<${tag}${attrText}>\n${code}\n</${tag}>`
}

function queryNodeText(attrs: Record<string, unknown>): string {
    const attrText =
        typeof attrs.title === 'string' && attrs.title.length > 0 ? ` title="${escapeAttribute(attrs.title)}"` : ''
    const query = isRecord(attrs.query) ? attrs.query : {}
    return `<query${attrText}>\n${JSON.stringify(query)}\n</query>`
}

export function documentTextContent(doc: ProseMirrorDoc): string {
    return doc.content
        .map(textContent)
        .filter((text) => text.length > 0)
        .join('\n')
}

function topLevelPositionAfter(doc: ProseMirrorDoc, index: number): number {
    let position = 0
    for (let i = 0; i <= index; i++) {
        const child = doc.content[i]
        if (!child) {
            break
        }
        position += nodeSize(child)
    }
    return position
}

function topLevelPositionBefore(doc: ProseMirrorDoc, index: number): number {
    let position = 0
    for (let i = 0; i < index; i++) {
        const child = doc.content[i]
        if (!child) {
            break
        }
        position += nodeSize(child)
    }
    return position
}

function cloneNodes(nodes: ProseMirrorNode[]): ProseMirrorNode[] {
    return cloneJson(nodes)
}

function textNode(text: string): ProseMirrorNode {
    return { type: 'text', text }
}

function paragraphNode(text: string): ProseMirrorNode {
    const trimmedText = text.trim()
    if (trimmedText.length === 0) {
        return { type: 'paragraph' }
    }
    return { type: 'paragraph', content: [textNode(trimmedText)] }
}

function headingNode(level: number, text: string): ProseMirrorNode {
    return { type: 'heading', attrs: { level }, content: [textNode(text.trim())] }
}

function listItemNode(text: string): ProseMirrorNode {
    return { type: 'listItem', content: [paragraphNode(text)] }
}

function codeBlockNode(code: string): ProseMirrorNode {
    const trimmedCode = code.replace(/\n+$/, '')
    if (trimmedCode.length === 0) {
        return { type: 'codeBlock' }
    }
    return { type: 'codeBlock', content: [textNode(trimmedCode)] }
}

function plainTextToNodes(content: string): ProseMirrorNode[] {
    return content
        .replace(/\r\n/g, '\n')
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line.length > 0)
        .map(paragraphNode)
}

export function contentUsesExecutableAnalysisBlocks(content: string | undefined): boolean {
    if (!content) {
        return false
    }
    EXECUTABLE_ANALYSIS_BLOCK_PATTERN.lastIndex = 0
    return EXECUTABLE_ANALYSIS_BLOCK_PATTERN.test(content)
}

function nodesUseExecutableAnalysisBlocks(nodes: ProseMirrorNode[] | undefined): boolean {
    if (!nodes) {
        return false
    }
    return nodes.some((node) => {
        if (EXECUTABLE_ANALYSIS_NODE_TYPES.has(node.type)) {
            return true
        }
        return nodesUseExecutableAnalysisBlocks(node.content)
    })
}

function editUsesExecutableAnalysisBlocks(edit: NotebookEdit): boolean {
    if (edit.type === 'replace_text') {
        return false
    }
    return contentUsesExecutableAnalysisBlocks(edit.content) || nodesUseExecutableAnalysisBlocks(edit.nodes)
}

export async function hasNotebookPythonFeatureFlag(context: Context): Promise<boolean> {
    try {
        const [distinctId, analyticsContext] = await Promise.all([
            context.getDistinctId(),
            context.stateManager.getAnalyticsContext().catch(() => undefined),
        ])
        return await isFeatureFlagEnabled(
            NOTEBOOK_PYTHON_FEATURE_FLAG,
            distinctId,
            analyticsContext ? buildMCPAnalyticsGroups(analyticsContext) : undefined
        )
    } catch {
        return false
    }
}

function decodeHtml(value: string): string {
    return value
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&')
}

function parseBlockAttributes(rawAttrs: string): Record<string, string> {
    const attrs: Record<string, string> = {}
    for (const match of rawAttrs.matchAll(ATTRIBUTE_PATTERN)) {
        const key = match[1]?.replace(/-/g, '_').toLowerCase()
        const rawValue = match[2]
        if (!key || rawValue === undefined) {
            continue
        }
        const value =
            (rawValue.startsWith('"') && rawValue.endsWith('"')) || (rawValue.startsWith("'") && rawValue.endsWith("'"))
                ? rawValue.slice(1, -1)
                : rawValue
        attrs[key] = decodeHtml(value)
    }
    return attrs
}

function analysisBlockToNode(tag: string, rawAttrs: string, rawBody: string): ProseMirrorNode {
    const attrs = parseBlockAttributes(rawAttrs)
    const body = decodeHtml(rawBody.replace(/^\n|\n$/g, ''))
    const title = attrs.title

    if (tag === 'python') {
        return {
            type: 'ph-python',
            attrs: {
                code: body,
                ...(title ? { title } : {}),
                __init: { showSettings: true },
            },
        }
    }

    if (tag === 'hogql' || tag === 'ducksql' || tag === 'duckdb') {
        const isHogql = tag === 'hogql'
        return {
            type: isHogql ? 'ph-hogql-sql' : 'ph-duck-sql',
            attrs: {
                code: body,
                returnVariable: attrs.return_variable ?? attrs.returnvariable ?? (isHogql ? 'hogql_df' : 'duck_df'),
                ...(title ? { title } : {}),
                __init: { showSettings: true },
            },
        }
    }

    if (tag === 'query') {
        try {
            const query = JSON.parse(body) as unknown
            if (isRecord(query)) {
                return { type: 'ph-query', attrs: { query, title } }
            }
        } catch {
            // Fall through to a visible placeholder.
        }
        return paragraphNode('[Invalid query JSON]')
    }

    return paragraphNode(`[Unsupported notebook block: ${tag}]`)
}

export function markdownToNodes(content: string): ProseMirrorNode[] {
    const nodes: ProseMirrorNode[] = []
    let lastEnd = 0
    for (const match of content.matchAll(ANALYSIS_BLOCK_PATTERN)) {
        nodes.push(...markdownToBasicNodes(content.slice(lastEnd, match.index)))
        const tag = match[1]
        const rawAttrs = match[2]
        const rawBody = match[3]
        if (tag && rawAttrs !== undefined && rawBody !== undefined) {
            nodes.push(analysisBlockToNode(tag.toLowerCase(), rawAttrs, rawBody))
        }
        lastEnd = (match.index ?? 0) + match[0].length
    }
    nodes.push(...markdownToBasicNodes(content.slice(lastEnd)))
    return nodes
}

function markdownToBasicNodes(content: string): ProseMirrorNode[] {
    const lines = content.replace(/\r\n/g, '\n').trim().split('\n')
    const nodes: ProseMirrorNode[] = []
    let paragraphLines: string[] = []
    let listType: 'bulletList' | 'orderedList' | null = null
    let listItems: string[] = []
    let codeLines: string[] | null = null

    const flushParagraph = (): void => {
        if (paragraphLines.length === 0) {
            return
        }
        nodes.push(paragraphNode(paragraphLines.join(' ')))
        paragraphLines = []
    }

    const flushList = (): void => {
        if (!listType || listItems.length === 0) {
            return
        }
        nodes.push({ type: listType, content: listItems.map(listItemNode) })
        listType = null
        listItems = []
    }

    const flushCodeBlock = (): void => {
        if (!codeLines) {
            return
        }
        nodes.push(codeBlockNode(codeLines.join('\n')))
        codeLines = null
    }

    for (const rawLine of lines) {
        const line = rawLine.trimEnd()
        const trimmedLine = line.trim()

        if (codeLines) {
            if (trimmedLine.startsWith('```')) {
                flushCodeBlock()
            } else {
                codeLines.push(line)
            }
            continue
        }

        if (trimmedLine.length === 0) {
            flushParagraph()
            flushList()
            continue
        }

        if (trimmedLine.startsWith('```')) {
            flushParagraph()
            flushList()
            codeLines = []
            continue
        }

        const headingMatch = /^(#{1,6})\s+(.+)$/.exec(trimmedLine)
        if (headingMatch) {
            flushParagraph()
            flushList()
            const headingMarks = headingMatch[1]
            const headingText = headingMatch[2]
            if (headingMarks && headingText) {
                nodes.push(headingNode(headingMarks.length, headingText))
            }
            continue
        }

        const bulletMatch = /^[-*]\s+(.+)$/.exec(trimmedLine)
        if (bulletMatch) {
            flushParagraph()
            if (listType !== 'bulletList') {
                flushList()
                listType = 'bulletList'
            }
            const itemText = bulletMatch[1]
            if (itemText) {
                listItems.push(itemText)
            }
            continue
        }

        const orderedMatch = /^\d+[.)]\s+(.+)$/.exec(trimmedLine)
        if (orderedMatch) {
            flushParagraph()
            if (listType !== 'orderedList') {
                flushList()
                listType = 'orderedList'
            }
            const itemText = orderedMatch[1]
            if (itemText) {
                listItems.push(itemText)
            }
            continue
        }

        flushList()
        paragraphLines.push(trimmedLine)
    }

    flushParagraph()
    flushList()
    flushCodeBlock()
    return nodes
}

function contentToNodes(content: string, contentFormat: 'markdown' | 'plain_text'): ProseMirrorNode[] {
    const nodes = contentFormat === 'plain_text' ? plainTextToNodes(content) : markdownToNodes(content)
    if (nodes.length === 0) {
        throw new Error('Notebook edit content must include non-empty text.')
    }
    return nodes
}

export function buildNotebookDocFromMarkdown(content: string): ProseMirrorDoc {
    const nodes = markdownToNodes(content)
    return {
        type: 'doc',
        content: nodes.length > 0 ? nodes : [{ type: 'paragraph' }],
    }
}

function resolveInsertNodes(
    editType: string,
    input: {
        content?: string | undefined
        content_format?: 'markdown' | 'plain_text' | undefined
        nodes?: ProseMirrorNode[] | undefined
    }
): ProseMirrorNode[] {
    const hasContent = input.content !== undefined
    const hasNodes = input.nodes !== undefined

    if (hasContent && hasNodes) {
        throw new Error(`Provide either content or nodes for ${editType}, not both.`)
    }

    if (hasNodes) {
        if (!input.nodes || input.nodes.length === 0) {
            throw new Error(`Provide at least one node for ${editType}.`)
        }
        return input.nodes
    }

    if (hasContent) {
        return contentToNodes(input.content ?? '', input.content_format ?? 'markdown')
    }

    throw new Error(`Provide content or nodes for ${editType}.`)
}

function applyAppendEdit(doc: ProseMirrorDoc, nodes: ProseMirrorNode[]): ReplaceStep {
    const position = documentContentSize(doc)
    const insertedNodes = cloneNodes(nodes)
    doc.content.push(...insertedNodes)
    return replaceStep(position, position, insertedNodes)
}

function applyInsertAfterHeadingEdit(
    doc: ProseMirrorDoc,
    heading: string,
    occurrence: number,
    nodes: ProseMirrorNode[]
): ReplaceStep {
    let matches = 0
    for (let index = 0; index < doc.content.length; index++) {
        const node = doc.content[index]
        if (!node || node.type !== 'heading' || textContent(node).trim() !== heading.trim()) {
            continue
        }

        matches += 1
        if (matches !== occurrence) {
            continue
        }

        const position = topLevelPositionAfter(doc, index)
        const insertedNodes = cloneNodes(nodes)
        doc.content.splice(index + 1, 0, ...insertedNodes)
        return replaceStep(position, position, insertedNodes)
    }

    throw new Error(`Could not find heading "${heading}" in the notebook.`)
}

function applyInsertAfterEdit(
    doc: ProseMirrorDoc,
    anchor: string,
    occurrence: number,
    nodes: ProseMirrorNode[]
): ReplaceStep {
    const index = findTopLevelAnchorIndex(doc, anchor, occurrence)
    if (index === null) {
        throw new Error(`Could not find text "${anchor}" in the notebook.`)
    }

    const position = topLevelPositionAfter(doc, index)
    const insertedNodes = cloneNodes(nodes)
    doc.content.splice(index + 1, 0, ...insertedNodes)
    return replaceStep(position, position, insertedNodes)
}

function applyInsertBeforeEdit(
    doc: ProseMirrorDoc,
    anchor: string,
    occurrence: number,
    nodes: ProseMirrorNode[]
): ReplaceStep {
    const index = findTopLevelAnchorIndex(doc, anchor, occurrence)
    if (index === null) {
        throw new Error(`Could not find text "${anchor}" in the notebook.`)
    }

    const position = topLevelPositionBefore(doc, index)
    const insertedNodes = cloneNodes(nodes)
    doc.content.splice(index, 0, ...insertedNodes)
    return replaceStep(position, position, insertedNodes)
}

function findTopLevelAnchorIndex(
    doc: ProseMirrorDoc,
    anchor: string,
    occurrence: number,
    startIndex: number = 0
): number | null {
    let matches = 0
    for (let index = startIndex; index < doc.content.length; index++) {
        const node = doc.content[index]
        if (!node || !textContent(node).includes(anchor)) {
            continue
        }

        matches += 1
        if (matches === occurrence) {
            return index
        }
    }

    return null
}

function applyInsertBetweenEdit(
    doc: ProseMirrorDoc,
    after: string,
    before: string,
    afterOccurrence: number,
    beforeOccurrence: number,
    nodes: ProseMirrorNode[]
): ReplaceStep {
    const afterIndex = findTopLevelAnchorIndex(doc, after, afterOccurrence)
    if (afterIndex === null) {
        throw new Error(`Could not find text "${after}" in the notebook.`)
    }

    const beforeIndex = findTopLevelAnchorIndex(doc, before, beforeOccurrence, afterIndex + 1)
    if (beforeIndex === null) {
        throw new Error(`Could not find text "${before}" after "${after}" in the notebook.`)
    }

    const position = topLevelPositionBefore(doc, beforeIndex)
    const insertedNodes = cloneNodes(nodes)
    doc.content.splice(beforeIndex, 0, ...insertedNodes)
    return replaceStep(position, position, insertedNodes)
}

function applyReplaceBlockEdit(
    doc: ProseMirrorDoc,
    anchor: string,
    occurrence: number,
    nodes: ProseMirrorNode[]
): ReplaceStep {
    const index = findTopLevelAnchorIndex(doc, anchor, occurrence)
    if (index === null) {
        throw new Error(`Could not find text "${anchor}" in the notebook.`)
    }

    const from = topLevelPositionBefore(doc, index)
    const to = topLevelPositionAfter(doc, index)
    const insertedNodes = cloneNodes(nodes)
    doc.content.splice(index, 1, ...insertedNodes)
    return replaceStep(from, to, insertedNodes)
}

function findTextMatch(
    node: ProseMirrorNode | ProseMirrorDoc,
    find: string,
    position: number,
    parent: ProseMirrorNode | ProseMirrorDoc | null = null,
    childIndex: number | null = null
): TextMatch | null {
    if (node.type === 'text') {
        const text = typeof node.text === 'string' ? node.text : ''
        const startIndex = text.indexOf(find)
        if (startIndex === -1) {
            return null
        }
        return {
            from: position + startIndex,
            to: position + startIndex + find.length,
            node,
            parent,
            childIndex,
            startIndex,
        }
    }

    if (!Array.isArray(node.content)) {
        return null
    }

    let childPosition = node.type === 'doc' ? position : position + 1
    for (let index = 0; index < node.content.length; index++) {
        const child = node.content[index]
        if (!child) {
            continue
        }
        const match = findTextMatch(child, find, childPosition, node, index)
        if (match) {
            return match
        }
        childPosition += nodeSize(child)
    }

    return null
}

function replacementTextNodes(match: TextMatch, replacement: string): ProseMirrorNode[] {
    if (replacement.length === 0) {
        return []
    }

    const node: ProseMirrorNode = { type: 'text', text: replacement }
    if (Array.isArray(match.node.marks)) {
        node.marks = cloneJson(match.node.marks)
    }
    return [node]
}

function applyTextReplacement(doc: ProseMirrorDoc, find: string, replacement: string): ReplaceStep | null {
    const match = findTextMatch(doc, find, 0)
    if (!match) {
        return null
    }

    const text = typeof match.node.text === 'string' ? match.node.text : ''
    match.node.text = `${text.slice(0, match.startIndex)}${replacement}${text.slice(match.startIndex + find.length)}`

    if (
        match.node.text.length === 0 &&
        match.parent &&
        match.childIndex !== null &&
        Array.isArray(match.parent.content)
    ) {
        match.parent.content.splice(match.childIndex, 1)
    }

    return replaceStep(match.from, match.to, replacementTextNodes(match, replacement))
}

function applyReplaceTextEdit(
    doc: ProseMirrorDoc,
    find: string,
    replacement: string,
    allOccurrences: boolean
): ReplaceStep[] {
    const steps: ReplaceStep[] = []

    while (true) {
        const step = applyTextReplacement(doc, find, replacement)
        if (!step) {
            break
        }

        steps.push(step)

        if (!allOccurrences) {
            break
        }

        if (steps.length >= MAX_TEXT_REPLACEMENTS) {
            throw new Error(
                `Stopped after ${MAX_TEXT_REPLACEMENTS} replacements for "${find}". Narrow the edit target.`
            )
        }
    }

    if (steps.length === 0) {
        throw new Error(`Could not find text "${find}" in the notebook.`)
    }

    return steps
}

function applyNotebookEdit(doc: ProseMirrorDoc, edit: NotebookEdit): ReplaceStep[] {
    switch (edit.type) {
        case 'append':
            return [applyAppendEdit(doc, resolveInsertNodes(edit.type, edit))]
        case 'insert_after_heading':
            return [
                applyInsertAfterHeadingEdit(
                    doc,
                    edit.heading,
                    edit.occurrence ?? 1,
                    resolveInsertNodes(edit.type, edit)
                ),
            ]
        case 'insert_after':
            return [applyInsertAfterEdit(doc, edit.anchor, edit.occurrence ?? 1, resolveInsertNodes(edit.type, edit))]
        case 'insert_before':
            return [applyInsertBeforeEdit(doc, edit.anchor, edit.occurrence ?? 1, resolveInsertNodes(edit.type, edit))]
        case 'insert_between':
            return [
                applyInsertBetweenEdit(
                    doc,
                    edit.after,
                    edit.before,
                    edit.after_occurrence ?? 1,
                    edit.before_occurrence ?? 1,
                    resolveInsertNodes(edit.type, edit)
                ),
            ]
        case 'replace_block':
            return [applyReplaceBlockEdit(doc, edit.anchor, edit.occurrence ?? 1, resolveInsertNodes(edit.type, edit))]
        case 'replace_text':
            return applyReplaceTextEdit(doc, edit.find, edit.replace, edit.all_occurrences ?? false)
    }
}

function buildEditPlan(content: unknown, edits: NotebookEdit[]): EditPlan {
    const doc = normalizeDocument(content)
    const steps = edits.flatMap((edit) => applyNotebookEdit(doc, edit))

    return {
        content: doc,
        steps,
        textContent: documentTextContent(doc),
    }
}

function makeClientId(): string {
    if (globalThis.crypto?.randomUUID) {
        return `mcp-${globalThis.crypto.randomUUID()}`
    }
    return `mcp-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function isRetryableCollabConflict(error: unknown): error is PostHogApiError {
    return error instanceof PostHogApiError && (error.status === 409 || error.status === 410)
}

function wait(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

async function retrieveNotebook(context: Context, projectId: string, shortId: string): Promise<Schemas.Notebook> {
    return await context.api.request<Schemas.Notebook>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(projectId)}/notebooks/${encodeURIComponent(shortId)}/`,
    })
}

async function submitCollabSave(
    context: Context,
    projectId: string,
    shortId: string,
    notebook: Schemas.Notebook,
    plan: EditPlan,
    title: string | undefined
): Promise<Schemas.Notebook> {
    const body: Record<string, unknown> = {
        client_id: makeClientId(),
        version: notebook.version ?? 0,
        steps: plan.steps,
        content: plan.content,
        text_content: plan.textContent,
    }
    if (title !== undefined) {
        body.title = title
    }

    return await context.api.request<Schemas.Notebook>({
        method: 'POST',
        path: `/api/projects/${encodeURIComponent(projectId)}/notebooks/${encodeURIComponent(shortId)}/collab/save/`,
        body,
    })
}

async function updateTitleOnly(
    context: Context,
    projectId: string,
    shortId: string,
    title: string
): Promise<Schemas.Notebook> {
    return await context.api.request<Schemas.Notebook>({
        method: 'PATCH',
        path: `/api/projects/${encodeURIComponent(projectId)}/notebooks/${encodeURIComponent(shortId)}/`,
        body: { title },
    })
}

const tool = (): ToolBase<typeof NotebookEditSchema, WithPostHogUrl<NotebookEditResult>> => ({
    name: 'notebooks-edit',
    schema: NotebookEditSchema,
    handler: async (context: Context, params: Params): Promise<WithPostHogUrl<NotebookEditResult>> => {
        const projectId = String(await context.stateManager.getProjectId())
        const maxRetries = Math.max(0, Math.min(params.max_retries ?? 3, 5))
        if (params.edits.some(editUsesExecutableAnalysisBlocks) && !(await hasNotebookPythonFeatureFlag(context))) {
            throw new Error(
                'Python, HogQL SQL, and DuckDB SQL notebook cells require the notebook-python feature flag. Use <query> nodes or saved insights for SQL analysis instead.'
            )
        }

        for (let attempt = 0; attempt <= maxRetries; attempt++) {
            const notebook = await retrieveNotebook(context, projectId, params.short_id)
            const plan = buildEditPlan(notebook.content, params.edits)

            if (plan.steps.length === 0) {
                if (params.title === undefined) {
                    throw new Error('No notebook edits were generated.')
                }
                const updatedTitle = await updateTitleOnly(context, projectId, params.short_id, params.title)
                return await withPostHogUrl(
                    context,
                    { ...updatedTitle, applied_edits: params.edits.length },
                    `/notebooks/${updatedTitle.short_id}`
                )
            }

            try {
                const updated = await submitCollabSave(
                    context,
                    projectId,
                    params.short_id,
                    notebook,
                    plan,
                    params.title
                )
                return await withPostHogUrl(
                    context,
                    { ...updated, applied_edits: params.edits.length },
                    `/notebooks/${updated.short_id}`
                )
            } catch (error) {
                if (!isRetryableCollabConflict(error) || attempt === maxRetries) {
                    if (isRetryableCollabConflict(error)) {
                        throw new Error(
                            `Could not apply notebook edit after ${maxRetries + 1} attempts because the notebook kept changing. Try again.`
                        )
                    }
                    throw error
                }

                await wait(25 * (attempt + 1))
            }
        }

        throw new Error('Could not apply notebook edit.')
    },
})

export default tool
