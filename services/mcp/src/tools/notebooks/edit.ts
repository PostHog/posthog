import { isDeepStrictEqual } from 'node:util'
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

const SubtreeReplaceEditSchema = z
    .object({
        type: z.literal('replace_subtree'),
        old_node: z
            .union([ProseMirrorNodeSchema, NodesSchema])
            .describe('exact ProseMirror node or node array to replace.'),
        new_nodes: NodesSchema.describe('replacement ProseMirror node array.'),
        replace_all: z
            .boolean()
            .default(false)
            .describe('Replace every exact subtree match instead of only the first.'),
    })
    .describe('Subtree replacement edit used by the notebook-edit old_value/new_value schema.')

const ReplaceTextEditSchema = z
    .object({
        type: z.literal('replace_text'),
        find: z
            .string()
            .min(1)
            .describe(
                'Exact text to find. This can match normal notebook text and SQL inside query, HogQL, or DuckDB nodes.'
            ),
        replace: z.string().describe('Replacement text. Use an empty string to delete the matching text.'),
        all_occurrences: z.boolean().default(false).describe('Replace every exact match instead of only the first.'),
        anchor: z
            .string()
            .min(1)
            .optional()
            .describe(
                'Optional exact text anchor for a top-level block. When set, only that block is searched, which is the safest way to edit a specific query node.'
            ),
        occurrence: z
            .number()
            .int()
            .min(1)
            .default(1)
            .describe('Which matching anchor block to use when anchor appears more than once.'),
    })
    .describe(
        'Replace exact text in notebook text or inside query/code node attributes. For small SQL changes, prefer this over replacing the whole query block.'
    )

export const NotebookEditSchema = z.object({
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
                SubtreeReplaceEditSchema,
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
const EXECUTABLE_ANALYSIS_BLOCK_ERROR =
    'Python, HogQL SQL, and DuckDB SQL notebook cells require the notebook-python feature flag. Use <query> nodes or saved insights for SQL analysis instead.'
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
    if (edit.type === 'replace_text' || edit.type === 'replace_subtree') {
        return edit.type === 'replace_subtree' && nodesUseExecutableAnalysisBlocks(edit.new_nodes)
    }
    return contentUsesExecutableAnalysisBlocks(edit.content) || nodesUseExecutableAnalysisBlocks(edit.nodes)
}

function collectExecutableAnalysisNodes(value: unknown, nodes: unknown[] = []): unknown[] {
    if (Array.isArray(value)) {
        for (const item of value) {
            collectExecutableAnalysisNodes(item, nodes)
        }
        return nodes
    }

    if (!isRecord(value)) {
        return nodes
    }

    const nodeType = value.type
    if (typeof nodeType === 'string' && EXECUTABLE_ANALYSIS_NODE_TYPES.has(nodeType)) {
        nodes.push(value)
        return nodes
    }

    for (const item of Object.values(value)) {
        collectExecutableAnalysisNodes(item, nodes)
    }
    return nodes
}

function executableAnalysisNodesChanged(before: ProseMirrorDoc, after: ProseMirrorDoc): boolean {
    return !isDeepStrictEqual(collectExecutableAnalysisNodes(before), collectExecutableAnalysisNodes(after))
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

type StringReplacementResult<T> = {
    value: T
    count: number
}
type TextReplacementResult = {
    step: ReplaceStep
    nextPosition: number
}

function replaceInString(
    value: string,
    find: string,
    replacement: string,
    allOccurrences: boolean
): StringReplacementResult<string> {
    if (!value.includes(find)) {
        return { value, count: 0 }
    }

    if (!allOccurrences) {
        return { value: value.replace(find, replacement), count: 1 }
    }

    return {
        value: value.split(find).join(replacement),
        count: value.split(find).length - 1,
    }
}

function replaceStringsInValue<T>(
    value: T,
    find: string,
    replacement: string,
    allOccurrences: boolean
): StringReplacementResult<T> {
    if (typeof value === 'string') {
        return replaceInString(value, find, replacement, allOccurrences) as StringReplacementResult<T>
    }

    if (Array.isArray(value)) {
        let count = 0
        const nextValue: unknown[] = []
        for (const item of value) {
            if (!allOccurrences && count > 0) {
                nextValue.push(item)
                continue
            }
            const result = replaceStringsInValue(item, find, replacement, allOccurrences)
            count += result.count
            nextValue.push(result.value)
        }
        return { value: nextValue as T, count }
    }

    if (isRecord(value)) {
        let count = 0
        const nextValue: Record<string, unknown> = {}
        for (const [key, item] of Object.entries(value)) {
            if (!allOccurrences && count > 0) {
                nextValue[key] = item
                continue
            }
            const result = replaceStringsInValue(item, find, replacement, allOccurrences)
            count += result.count
            nextValue[key] = result.value
        }
        return { value: nextValue as T, count }
    }

    return { value, count: 0 }
}

function replaceStringsInNodeAttrs(
    node: ProseMirrorNode,
    find: string,
    replacement: string,
    allOccurrences: boolean
): StringReplacementResult<ProseMirrorNode> {
    if (!isRecord(node.attrs)) {
        return { value: node, count: 0 }
    }

    const attrsResult = replaceStringsInValue(node.attrs, find, replacement, allOccurrences)
    if (attrsResult.count === 0) {
        return { value: node, count: 0 }
    }

    return {
        value: {
            ...node,
            attrs: attrsResult.value,
        },
        count: attrsResult.count,
    }
}

function applyAttributeReplacementInBlock(
    doc: ProseMirrorDoc,
    index: number,
    find: string,
    replacement: string,
    allOccurrences: boolean
): ReplaceStep[] {
    const node = doc.content[index]
    if (!node) {
        return []
    }

    const result = replaceStringsInNodeAttrs(node, find, replacement, allOccurrences)
    if (result.count === 0) {
        return []
    }

    const from = topLevelPositionBefore(doc, index)
    const to = topLevelPositionAfter(doc, index)
    const insertedNode = cloneJson(result.value)
    doc.content.splice(index, 1, insertedNode)
    return [replaceStep(from, to, [insertedNode])]
}

function findAttributeReplacementBlockIndex(
    doc: ProseMirrorDoc,
    find: string,
    startIndex: number = 0,
    endIndex: number = doc.content.length
): number | null {
    for (let index = startIndex; index < endIndex; index++) {
        const node = doc.content[index]
        if (!node || !textContent(node).includes(find)) {
            continue
        }
        if (replaceStringsInNodeAttrs(node, find, find, false).count > 0) {
            return index
        }
    }

    return null
}

function headingLevel(node: ProseMirrorNode): number | null {
    if (node.type !== 'heading' || !isRecord(node.attrs) || typeof node.attrs.level !== 'number') {
        return null
    }
    return node.attrs.level
}

function findSectionEndIndex(doc: ProseMirrorDoc, headingIndex: number): number {
    const heading = doc.content[headingIndex]
    if (!heading) {
        return headingIndex + 1
    }

    const level = headingLevel(heading)
    if (level === null) {
        return headingIndex + 1
    }

    for (let index = headingIndex + 1; index < doc.content.length; index++) {
        const node = doc.content[index]
        if (!node) {
            continue
        }
        const nextLevel = headingLevel(node)
        if (nextLevel !== null && nextLevel <= level) {
            return index
        }
    }

    return doc.content.length
}

function blockRangeForAnchor(doc: ProseMirrorDoc, anchorIndex: number): { startIndex: number; endIndex: number } {
    const anchorNode = doc.content[anchorIndex]
    if (anchorNode?.type !== 'heading') {
        return { startIndex: anchorIndex, endIndex: anchorIndex + 1 }
    }

    return { startIndex: anchorIndex + 1, endIndex: findSectionEndIndex(doc, anchorIndex) }
}

function applyTextReplacementInBlock(
    doc: ProseMirrorDoc,
    index: number,
    find: string,
    replacement: string,
    startPosition: number = 0
): TextReplacementResult | null {
    const node = doc.content[index]
    if (!node) {
        return null
    }

    const match = findTextMatch(node, find, topLevelPositionBefore(doc, index), null, null, startPosition)
    if (!match) {
        return null
    }

    return {
        step: applyTextMatchReplacement(match, find, replacement),
        nextPosition: match.from + replacement.length,
    }
}

function applyReplacementsInBlockRange(
    doc: ProseMirrorDoc,
    startIndex: number,
    endIndex: number,
    find: string,
    replacement: string,
    allOccurrences: boolean
): ReplaceStep[] {
    const steps: ReplaceStep[] = []
    let replacements = 0

    for (let index = startIndex; index < endIndex; index++) {
        const attributeSteps = applyAttributeReplacementInBlock(doc, index, find, replacement, allOccurrences)
        if (attributeSteps.length > 0) {
            steps.push(...attributeSteps)
            replacements += attributeSteps.length
            if (!allOccurrences) {
                return steps
            }
            assertReplacementLimit(find, replacements)
            continue
        }

        let searchPosition = topLevelPositionBefore(doc, index)
        while (true) {
            const textReplacement = applyTextReplacementInBlock(doc, index, find, replacement, searchPosition)
            if (!textReplacement) {
                break
            }

            steps.push(textReplacement.step)
            searchPosition = textReplacement.nextPosition
            replacements += 1

            if (!allOccurrences) {
                return steps
            }

            assertReplacementLimit(find, replacements)
        }
    }

    return steps
}

function findTextMatch(
    node: ProseMirrorNode | ProseMirrorDoc,
    find: string,
    position: number,
    parent: ProseMirrorNode | ProseMirrorDoc | null = null,
    childIndex: number | null = null,
    startPosition: number = 0
): TextMatch | null {
    if (node.type === 'text') {
        const text = typeof node.text === 'string' ? node.text : ''
        const localStartIndex = Math.max(0, startPosition - position)
        const startIndex = text.indexOf(find, localStartIndex)
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
        const match = findTextMatch(child, find, childPosition, node, index, startPosition)
        if (match) {
            return match
        }
        childPosition += nodeSize(child)
    }

    return null
}

function findExactTextNodeMatch(
    node: ProseMirrorNode | ProseMirrorDoc,
    find: string,
    position: number,
    parent: ProseMirrorNode | ProseMirrorDoc | null = null,
    childIndex: number | null = null
): TextMatch | null {
    if (node.type === 'text') {
        if (node.text !== find) {
            return null
        }
        return {
            from: position,
            to: position + find.length,
            node,
            parent,
            childIndex,
            startIndex: 0,
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
        const match = findExactTextNodeMatch(child, find, childPosition, node, index)
        if (match) {
            return match
        }
        childPosition += nodeSize(child)
    }

    return null
}

function countExactTextNodeMatches(node: ProseMirrorNode | ProseMirrorDoc, find: string): number {
    if (node.type === 'text') {
        return node.text === find ? 1 : 0
    }
    if (!Array.isArray(node.content)) {
        return 0
    }
    return node.content.reduce((count, child) => count + countExactTextNodeMatches(child, find), 0)
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

function applyTextMatchReplacement(match: TextMatch, find: string, replacement: string): ReplaceStep {
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

function applyTextReplacement(
    doc: ProseMirrorDoc,
    find: string,
    replacement: string,
    startPosition: number = 0
): TextReplacementResult | null {
    const match = findTextMatch(doc, find, 0, null, null, startPosition)
    if (!match) {
        return null
    }

    return {
        step: applyTextMatchReplacement(match, find, replacement),
        nextPosition: match.from + replacement.length,
    }
}

function applyExactTextNodeReplacementEdit(
    doc: ProseMirrorDoc,
    find: string,
    replacement: string,
    allOccurrences: boolean
): ReplaceStep[] {
    const matches = countExactTextNodeMatches(doc, find)
    if (matches === 0) {
        throw new Error(`Could not find text node "${find}" in the notebook.`)
    }
    if (matches > 1 && !allOccurrences) {
        throw new Error(`Text node "${find}" matches ${matches} places in the notebook content. Set replace_all.`)
    }

    const steps: ReplaceStep[] = []
    while (true) {
        const match = findExactTextNodeMatch(doc, find, 0)
        if (!match) {
            break
        }
        steps.push(applyTextMatchReplacement(match, find, replacement))
        if (!allOccurrences) {
            break
        }
        assertReplacementLimit(find, steps.length)
    }
    return steps
}

function assertReplacementLimit(find: string, replacementCount: number): void {
    if (replacementCount > MAX_TEXT_REPLACEMENTS) {
        throw new Error(`Stopped after ${MAX_TEXT_REPLACEMENTS} replacements for "${find}". Narrow the edit target.`)
    }
}

function countNodeMatches(node: ProseMirrorNode | ProseMirrorDoc | ProseMirrorNode[], target: unknown): number {
    let count = 0
    const walk = (value: unknown): void => {
        if (isDeepStrictEqual(value, target)) {
            count++
            return
        }
        if (Array.isArray(value)) {
            value.forEach(walk)
        } else if (isRecord(value)) {
            Object.values(value).forEach(walk)
        }
    }
    walk(node)
    return count
}

function nodesEqual(left: ProseMirrorNode | ProseMirrorNode[], right: ProseMirrorNode | ProseMirrorNode[]): boolean {
    return isDeepStrictEqual(left, right)
}

function topLevelSequenceMatches(doc: ProseMirrorDoc, startIndex: number, target: ProseMirrorNode[]): boolean {
    if (startIndex + target.length > doc.content.length) {
        return false
    }
    return target.every((targetNode, offset) => {
        const node = doc.content[startIndex + offset]
        return !!node && nodesEqual(node, targetNode)
    })
}

function countTopLevelSequenceMatches(doc: ProseMirrorDoc, target: ProseMirrorNode[]): number {
    let count = 0
    for (let index = 0; index <= doc.content.length - target.length; index++) {
        if (topLevelSequenceMatches(doc, index, target)) {
            count++
        }
    }
    return count
}

function applySubtreeReplacementEdit(
    doc: ProseMirrorDoc,
    oldNode: ProseMirrorNode | ProseMirrorNode[],
    newNodes: ProseMirrorNode[],
    replaceAll: boolean
): ReplaceStep[] {
    const target = oldNode
    const isTopLevelNodeArray = Array.isArray(target)
    const matches = isTopLevelNodeArray ? countTopLevelSequenceMatches(doc, target) : countNodeMatches(doc, target)
    if (matches === 0) {
        throw new Error('old_node was not found in the notebook content.')
    }
    if (matches > 1 && !replaceAll) {
        throw new Error(
            `old_node matches ${matches} places in the notebook content. Use a more specific node or set replace_all.`
        )
    }

    const steps: ReplaceStep[] = []
    for (let index = 0; index < doc.content.length; index++) {
        const node = doc.content[index]
        const targetLength = isTopLevelNodeArray ? target.length : 1
        if (
            (isTopLevelNodeArray && !topLevelSequenceMatches(doc, index, target)) ||
            (!isTopLevelNodeArray && (!node || !nodesEqual(node, target)))
        ) {
            continue
        }
        const from = topLevelPositionBefore(doc, index)
        const to = topLevelPositionAfter(doc, index + targetLength - 1)
        const insertedNodes = cloneNodes(newNodes)
        doc.content.splice(index, targetLength, ...insertedNodes)
        steps.push(replaceStep(from, to, insertedNodes))
        if (!replaceAll) {
            break
        }
        index += insertedNodes.length - 1
    }

    if (steps.length === 0) {
        throw new Error(
            'old_node was not found as a top-level notebook block. Use the anchored edits schema for nested replacements.'
        )
    }
    return steps
}

function applyReplaceTextEdit(
    doc: ProseMirrorDoc,
    find: string,
    replacement: string,
    allOccurrences: boolean,
    anchor?: string,
    occurrence: number = 1,
    legacyTextNodeReplacement: boolean = false
): ReplaceStep[] {
    if (anchor) {
        const index = findTopLevelAnchorIndex(doc, anchor, occurrence)
        if (index === null) {
            throw new Error(`Could not find text "${anchor}" in the notebook.`)
        }

        const range = blockRangeForAnchor(doc, index)
        const steps = applyReplacementsInBlockRange(
            doc,
            range.startIndex,
            range.endIndex,
            find,
            replacement,
            allOccurrences
        )
        if (steps.length > 0) {
            return steps
        }

        throw new Error(`Could not find text "${find}" inside notebook block or section anchored by "${anchor}".`)
    }

    if (legacyTextNodeReplacement) {
        return applyExactTextNodeReplacementEdit(doc, find, replacement, allOccurrences)
    }

    const steps: ReplaceStep[] = []
    let replacements = 0

    if (allOccurrences) {
        for (let index = 0; index < doc.content.length; index++) {
            const attributeSteps = applyAttributeReplacementInBlock(doc, index, find, replacement, true)
            steps.push(...attributeSteps)
            replacements += attributeSteps.length
            assertReplacementLimit(find, replacements)
        }

        let searchPosition = 0
        while (true) {
            const textReplacement = applyTextReplacement(doc, find, replacement, searchPosition)
            if (!textReplacement) {
                break
            }
            steps.push(textReplacement.step)
            searchPosition = textReplacement.nextPosition
            replacements += 1
            assertReplacementLimit(find, replacements)
        }

        if (steps.length === 0) {
            throw new Error(`Could not find text "${find}" in the notebook.`)
        }

        return steps
    }

    while (true) {
        const attributeIndex = findAttributeReplacementBlockIndex(doc, find)
        if (attributeIndex !== null) {
            const attributeSteps = applyAttributeReplacementInBlock(doc, attributeIndex, find, replacement, false)
            steps.push(...attributeSteps)
            replacements += attributeSteps.length
        } else {
            const textReplacement = applyTextReplacement(doc, find, replacement)
            if (!textReplacement) {
                break
            }
            steps.push(textReplacement.step)
            replacements += 1
        }

        break
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
            return applyReplaceTextEdit(
                doc,
                edit.find,
                edit.replace,
                edit.all_occurrences ?? false,
                edit.anchor,
                edit.occurrence ?? 1,
                (edit as { legacy_text_node_replacement?: boolean }).legacy_text_node_replacement === true
            )
        case 'replace_subtree':
            return applySubtreeReplacementEdit(doc, edit.old_node, edit.new_nodes, edit.replace_all ?? false)
    }
}

export function buildEditPlan(content: unknown, edits: NotebookEdit[]): EditPlan {
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
    name: 'notebook-edit',
    schema: NotebookEditSchema,
    handler: async (context: Context, params: Params): Promise<WithPostHogUrl<NotebookEditResult>> => {
        const projectId = String(await context.stateManager.getProjectId())
        const maxRetries = Math.max(0, Math.min(params.max_retries ?? 3, 5))
        let allowExecutableAnalysisBlocks: boolean | undefined
        const getAllowExecutableAnalysisBlocks = async (): Promise<boolean> => {
            if (allowExecutableAnalysisBlocks === undefined) {
                allowExecutableAnalysisBlocks = await hasNotebookPythonFeatureFlag(context)
            }
            return allowExecutableAnalysisBlocks
        }

        if (params.edits.some(editUsesExecutableAnalysisBlocks) && !(await getAllowExecutableAnalysisBlocks())) {
            throw new Error(EXECUTABLE_ANALYSIS_BLOCK_ERROR)
        }

        for (let attempt = 0; attempt <= maxRetries; attempt++) {
            const notebook = await retrieveNotebook(context, projectId, params.short_id)
            const originalContent = normalizeDocument(notebook.content)
            const plan = buildEditPlan(notebook.content, params.edits)
            if (
                executableAnalysisNodesChanged(originalContent, plan.content) &&
                !(await getAllowExecutableAnalysisBlocks())
            ) {
                throw new Error(EXECUTABLE_ANALYSIS_BLOCK_ERROR)
            }

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
