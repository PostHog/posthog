/**
 * Utilities for reading and writing notebook cell component tags inside markdown-notebook
 * documents (`<SQLV2 … />`, `<PythonV2 … />`, `<Query … />`).
 *
 * The format contract mirrors frontend/src/lib/components/MarkdownNotebook/markdown.ts:
 * - Cells are self-closing block-level tags. The parser never stores a tag body, so code
 *   must ride the `code` prop as a JSON-escaped string (a literal blank line inside a tag
 *   would end the parser's block scan and corrupt the cell).
 * - String props serialize via JSON.stringify; object/boolean props as `{<json>}`.
 * - `nodeId` is the durable cell identity (parsed block ids are content fingerprints that
 *   change whenever any prop changes, e.g. when a run writes runId/result back).
 */

export const COMPONENT_TAG_REGEX = /^[A-Z][A-Za-z0-9]*$/

export interface CellTagBlock {
    tagName: string
    /** Character offsets of the tag block within the markdown, end exclusive. */
    start: number
    end: number
    source: string
    nodeId: string | null
    returnVariable: string
    code: string
}

export const DATAFRAME_NAME_REGEX = /^[A-Za-z_][A-Za-z0-9_]*$/

const TAG_START_REGEX = /^<([A-Z][A-Za-z0-9]*)(?=[\s/>])/

// A JSON string literal: quote-delimited with backslash escapes.
const JSON_STRING = '"(?:[^"\\\\]|\\\\.)*"'

function stringPropRegex(name: string): RegExp {
    return new RegExp(`(^|\\s)${name}=(${JSON_STRING})`, 'm')
}

export function readStringProp(tagSource: string, name: string): string | null {
    const match = tagSource.match(stringPropRegex(name))
    if (!match) {
        return null
    }
    try {
        return JSON.parse(match[2]!) as string
    } catch {
        return null
    }
}

/** Locate an `name={…}` expression prop; returns offsets of the whole `name={…}` segment. */
function findExpressionProp(tagSource: string, name: string): { start: number; end: number } | null {
    const marker = new RegExp(`(^|\\s)${name}=\\{`, 'm').exec(tagSource)
    if (!marker) {
        return null
    }
    const braceStart = marker.index + marker[0].length - 1
    let depth = 0
    let inString = false
    for (let i = braceStart; i < tagSource.length; i++) {
        const char = tagSource[i]
        if (inString) {
            if (char === '\\') {
                i += 1
            } else if (char === '"') {
                inString = false
            }
            continue
        }
        if (char === '"') {
            inString = true
        } else if (char === '{') {
            depth += 1
        } else if (char === '}') {
            depth -= 1
            if (depth === 0) {
                return { start: marker.index + (marker[1]?.length ?? 0), end: i + 1 }
            }
        }
    }
    return null
}

export function serializePropValue(value: unknown): string {
    if (typeof value === 'string') {
        return JSON.stringify(value)
    }
    return `{${JSON.stringify(value)}}`
}

/** Set or replace a prop on a self-closing tag, preserving every other prop untouched. */
export function upsertProp(tagSource: string, name: string, value: unknown): string {
    const serialized = `${name}=${serializePropValue(value)}`
    const stringMatch = stringPropRegex(name).exec(tagSource)
    if (stringMatch) {
        const start = stringMatch.index + stringMatch[1]!.length
        return tagSource.slice(0, start) + serialized + tagSource.slice(stringMatch.index + stringMatch[0].length)
    }
    const expression = findExpressionProp(tagSource, name)
    if (expression) {
        return tagSource.slice(0, expression.start) + serialized + tagSource.slice(expression.end)
    }
    const closing = tagSource.lastIndexOf('/>')
    if (closing === -1) {
        throw new Error(`Cell tag is not self-closing: ${tagSource.slice(0, 80)}`)
    }
    const needsSpace = closing > 0 && !/\s/.test(tagSource[closing - 1]!)
    return `${tagSource.slice(0, closing)}${needsSpace ? ' ' : ''}${serialized} ${tagSource.slice(closing)}`
}

export function buildCellTag(tagName: string, props: Record<string, unknown>): string {
    const serialized = Object.entries(props)
        .filter(([, value]) => value !== undefined)
        .map(([name, value]) => `${name}=${serializePropValue(value)}`)
        .join(' ')
    return `<${tagName}${serialized ? ` ${serialized}` : ''} />`
}

/**
 * Scan the markdown for cell tag blocks. Mirrors the frontend block scanner: a tag block
 * starts at a line beginning with `<TagName` and runs until a line ending in `/>` (or a
 * closing tag) — a blank line terminates an unclosed tag without swallowing the document.
 */
export function parseCellTags(markdown: string): CellTagBlock[] {
    const blocks: CellTagBlock[] = []
    const lines = markdown.split('\n')
    let offset = 0
    let index = 0
    while (index < lines.length) {
        const line = lines[index]!
        const startMatch = TAG_START_REGEX.exec(line.trim())
        if (!startMatch) {
            offset += line.length + 1
            index += 1
            continue
        }
        const tagName = startMatch[1]!
        const blockLines: string[] = []
        let cursor = index
        let terminated = false
        while (cursor < lines.length && (cursor === index || lines[cursor]!.trim())) {
            blockLines.push(lines[cursor]!)
            const raw = blockLines.join('\n').trim()
            if (raw.endsWith('/>') || raw.includes(`</${tagName}>`)) {
                terminated = true
                break
            }
            cursor += 1
        }
        if (!terminated) {
            offset += line.length + 1
            index += 1
            continue
        }
        const source = blockLines.join('\n')
        const start = offset
        blocks.push({
            tagName,
            start,
            end: start + source.length,
            source,
            nodeId: readStringProp(source, 'nodeId'),
            returnVariable: (readStringProp(source, 'returnVariable') ?? '').trim(),
            code: readStringProp(source, 'code') ?? '',
        })
        offset += blockLines.reduce((sum, blockLine) => sum + blockLine.length + 1, 0)
        index = cursor + 1
    }
    return blocks
}

export function findCellTag(markdown: string, nodeId: string): CellTagBlock | null {
    return parseCellTags(markdown).find((block) => block.nodeId === nodeId) ?? null
}

export function replaceCellTag(markdown: string, block: CellTagBlock, nextSource: string): string {
    return markdown.slice(0, block.start) + nextSource + markdown.slice(block.end)
}

/** Remove a tag block along with one adjacent blank separator line so no gap is left behind. */
export function removeCellTag(markdown: string, block: CellTagBlock): string {
    let start = block.start
    let end = block.end
    if (markdown.slice(end, end + 2) === '\n\n') {
        end += 2
    } else if (markdown.slice(start - 2, start) === '\n\n') {
        start -= 2
    }
    return markdown.slice(0, start) + markdown.slice(end)
}

/**
 * Every named sibling cell, keyed by dataframe name — the run endpoint filters to what the
 * code actually references. SQL cells win name collisions, matching the frontend collector.
 */
export function collectRunRefs(
    cells: CellTagBlock[],
    selfNodeId: string
): Record<string, { node_id: string; kind: 'hogql' | 'local' }> {
    const refs: Record<string, { node_id: string; kind: 'hogql' | 'local' }> = {}
    for (const cell of cells) {
        if (cell.tagName !== 'SQLV2' || !cell.nodeId || cell.nodeId === selfNodeId) {
            continue
        }
        if (DATAFRAME_NAME_REGEX.test(cell.returnVariable)) {
            refs[cell.returnVariable] = { node_id: cell.nodeId, kind: 'hogql' }
        }
    }
    for (const cell of cells) {
        if (cell.tagName !== 'PythonV2' || !cell.nodeId || cell.nodeId === selfNodeId) {
            continue
        }
        if (DATAFRAME_NAME_REGEX.test(cell.returnVariable) && !(cell.returnVariable in refs)) {
            refs[cell.returnVariable] = { node_id: cell.nodeId, kind: 'local' }
        }
    }
    return refs
}

/** Cells whose code references the given dataframe name as a bare identifier. */
export function directDependents(
    cells: CellTagBlock[],
    dataframeName: string,
    selfNodeId: string
): { node_id: string; dataframe_name?: string }[] {
    if (!DATAFRAME_NAME_REGEX.test(dataframeName)) {
        return []
    }
    const reference = new RegExp(`\\b${dataframeName}\\b`)
    const dependents: { node_id: string; dataframe_name?: string }[] = []
    for (const cell of cells) {
        if (cell.nodeId === selfNodeId || !cell.nodeId || (cell.tagName !== 'SQLV2' && cell.tagName !== 'PythonV2')) {
            continue
        }
        if (reference.test(cell.code)) {
            dependents.push({
                node_id: cell.nodeId,
                ...(cell.returnVariable ? { dataframe_name: cell.returnVariable } : {}),
            })
        }
    }
    return dependents
}

export function uniqueDataframeName(base: string, cells: CellTagBlock[]): string {
    const used = new Set(cells.map((cell) => cell.returnVariable.toLowerCase()).filter(Boolean))
    if (!used.has(base.toLowerCase())) {
        return base
    }
    let suffix = 2
    while (used.has(`${base}_${suffix}`.toLowerCase())) {
        suffix += 1
    }
    return `${base}_${suffix}`
}
