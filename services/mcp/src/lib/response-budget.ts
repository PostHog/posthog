/**
 * Bounds one tool result so a client never has to cut it, which Codex does mid-value.
 * JSON and TOON are re-serialized from a projection, so the output stays parseable.
 */

import { formatResponse } from '@/lib/response'

/** Codex converts a token limit to bytes at this rate, so a budget here is measured the same way. */
const BYTES_PER_TOKEN = 4

/**
 * Ceiling for clients that read a large tool result whole. It sits below the 500,000-character
 * hard ceiling Claude Code applies to a tool's text result, and above the p90 size of every
 * tool except the outliers it exists to stop.
 */
export const DEFAULT_MAX_RESPONSE_TOKENS = 100_000

export const RESPONSE_BUDGET_KEY = '_responseBudget'

const NOTICE_RESERVE_BYTES = 1_024
/** Entries this small are kept before bulk fields, so ids, URLs, counts and tool notices survive. */
const POINTER_ENTRY_BYTES = 512
/** A string shorter than this after cutting carries no useful head, so it is dropped instead. */
const MIN_STRING_KEEP_BYTES = 64
const MAX_PROJECTION_DEPTH = 6
const MAX_FIT_ATTEMPTS = 6
const MAX_LISTED_CUTS = 5
const POINTER_LINE = /^(_posthogUrl|_agentNote): /
/** A bracketed last line is a tool's own notice, such as the execute-sql preview line. */
const TRAILING_NOTICE_LINE = /^\[.*\]$/
const INFORMATIONAL_OPEN_TAG = /<([A-Za-z0-9_-]+) informational="true" instructional="false">\n/

export interface ResponseBodySource {
    value: unknown
    serialize: (value: unknown) => string
}

export function byteLength(text: string): number {
    return Buffer.byteLength(text, 'utf8')
}

export function maxResponseBytes(maxTokens: number): number {
    return maxTokens * BYTES_PER_TOKEN
}

/** `truncate: false` asks for the complete result, so only a client's own limit applies to it. */
export function responseTokenBudget(clientLimit: number | undefined, args: unknown): number | undefined {
    if (clientLimit !== undefined) {
        return clientLimit
    }
    const wantsFullResult =
        typeof args === 'object' && args !== null && (args as Record<string, unknown>).truncate === false
    return wantsFullResult ? undefined : DEFAULT_MAX_RESPONSE_TOKENS
}

function jsonBytes(value: unknown): number {
    try {
        const text = JSON.stringify(value)
        return text === undefined ? 0 : byteLength(text)
    } catch {
        return Number.POSITIVE_INFINITY
    }
}

function formatTokens(tokens: number): string {
    return tokens >= 1000 ? `${Math.round(tokens / 1000)}K` : String(tokens)
}

function overflowNotice(fullBytes: number, maxTokens: number, cuts: string[]): string {
    const listed = cuts.slice(0, MAX_LISTED_CUTS).join('; ')
    const more = cuts.length > MAX_LISTED_CUTS ? `; and ${cuts.length - MAX_LISTED_CUTS} more` : ''
    return (
        `[Response shortened to about ${formatTokens(maxTokens)} tokens, the most this client accepts in one tool result. ` +
        `The full result is about ${formatTokens(Math.ceil(fullBytes / BYTES_PER_TOKEN))} tokens. ` +
        (cuts.length > 0 ? `Shortened: ${listed}${more}. ` : '') +
        'To get the rest, ask for less per call: page with the tool’s limit/offset or cursor, add filters, ' +
        'shorten the date range, or request fewer fields.]'
    )
}

function prefixWithinBytes(text: string, maxBytes: number): string {
    let end = Math.min(text.length, maxBytes)
    while (end > 0 && byteLength(text.slice(0, end)) > maxBytes) {
        end = Math.floor((end * maxBytes) / byteLength(text.slice(0, end)))
    }
    const last = text.charCodeAt(end - 1)
    return last >= 0xd800 && last <= 0xdbff ? text.slice(0, end - 1) : text.slice(0, end)
}

/** When no whole line fits, the first line is cut and marked, so a single-line body keeps its head. */
export function clipLines(text: string, maxBytes: number): { text: string; cut: string } {
    let prefix = ''
    let body = text
    let suffix = ''
    const open = INFORMATIONAL_OPEN_TAG.exec(text)
    if (open) {
        const bodyStart = open.index + open[0].length
        const closeIndex = text.lastIndexOf(`\n</${open[1]}>`)
        if (closeIndex >= bodyStart) {
            prefix = text.slice(0, bodyStart)
            body = text.slice(bodyStart, closeIndex)
            suffix = text.slice(closeIndex)
        }
    }

    const lines = body.split('\n')
    const pointers = lines.filter(
        (line, index) => POINTER_LINE.test(line) || (index === lines.length - 1 && TRAILING_NOTICE_LINE.test(line))
    )
    let rows = lines.filter((line) => !pointers.includes(line))
    let room = maxBytes - byteLength(prefix) - byteLength(suffix) - byteLength(pointers.join('\n')) - 1
    if (room < MIN_STRING_KEEP_BYTES) {
        prefix = suffix = ''
        pointers.length = 0
        rows = text.split('\n')
        room = maxBytes
    }

    const kept: string[] = []
    let spent = 0
    for (const row of rows) {
        const cost = byteLength(row) + (kept.length > 0 ? 1 : 0)
        if (spent + cost > room) {
            break
        }
        kept.push(row)
        spent += cost
    }
    let cut = `kept ${kept.length} of ${rows.length} lines`
    if (kept.length === 0 && rows.length > 0) {
        const marker = ' …[line cut]'
        kept.push(prefixWithinBytes(rows[0]!, Math.max(0, room - byteLength(marker))) + marker)
        cut = `kept the start of line 1 of ${rows.length}`
    }
    return { text: prefix + [...kept, ...pointers].join('\n') + suffix, cut }
}

const DROPPED = Symbol('dropped')

function projectString(value: string, budget: number, path: string, cuts: string[]): string | typeof DROPPED {
    // Two bytes for the quotes, plus room for escapes JSON adds to the kept head.
    const room = budget - 2 - Math.ceil(budget / 10)
    if (room < MIN_STRING_KEEP_BYTES) {
        cuts.push(`${path || 'value'} omitted`)
        return DROPPED
    }
    const clipped = value.includes('\n')
        ? clipLines(value, room)
        : { text: `${prefixWithinBytes(value, room - 16)} …[cut]`, cut: `shortened from ${value.length} characters` }
    cuts.push(`${path || 'value'}: ${clipped.cut}`)
    return clipped.text
}

function projectArray(value: unknown[], budget: number, path: string, cuts: string[], depth: number): unknown[] {
    const kept: unknown[] = []
    let spent = 2
    for (const item of value) {
        const cost = jsonBytes(item) + (kept.length > 0 ? 1 : 0)
        if (spent + cost <= budget) {
            kept.push(item)
            spent += cost
            continue
        }
        if (kept.length === 0) {
            const projected = project(item, budget - spent, `${path}[0]`, cuts, depth + 1)
            if (projected !== DROPPED) {
                kept.push(projected)
            }
        }
        break
    }
    if (kept.length < value.length) {
        cuts.push(`${path || 'items'}: kept ${kept.length} of ${value.length} items`)
    }
    return kept
}

function projectRecord(
    value: Record<string, unknown>,
    budget: number,
    path: string,
    cuts: string[],
    depth: number
): Record<string, unknown> {
    const entries = Object.entries(value)
    const kept = new Map<string, unknown>()
    let spent = 2
    const entryBytes = (key: string, entryValue: unknown): number =>
        byteLength(JSON.stringify(key)) + jsonBytes(entryValue) + 2

    for (const [key, entryValue] of entries) {
        const cost = entryBytes(key, entryValue)
        if (cost <= POINTER_ENTRY_BYTES && spent + cost <= budget) {
            kept.set(key, entryValue)
            spent += cost
        }
    }
    for (const [key, entryValue] of entries) {
        if (kept.has(key)) {
            continue
        }
        const childPath = path ? `${path}.${key}` : key
        const cost = entryBytes(key, entryValue)
        if (spent + cost <= budget) {
            kept.set(key, entryValue)
            spent += cost
            continue
        }
        const keyCost = byteLength(JSON.stringify(key)) + 2
        const projected = project(entryValue, budget - spent - keyCost, childPath, cuts, depth + 1)
        if (projected === DROPPED) {
            continue
        }
        kept.set(key, projected)
        spent += keyCost + jsonBytes(projected)
    }
    return Object.fromEntries(entries.filter(([key]) => kept.has(key)).map(([key]) => [key, kept.get(key)]))
}

function project(value: unknown, budget: number, path: string, cuts: string[], depth: number): unknown {
    if (jsonBytes(value) <= budget) {
        return value
    }
    if (typeof value === 'string') {
        return projectString(value, budget, path, cuts)
    }
    if (depth < MAX_PROJECTION_DEPTH && Array.isArray(value)) {
        return projectArray(value, budget, path, cuts, depth)
    }
    if (depth < MAX_PROJECTION_DEPTH && typeof value === 'object' && value !== null) {
        return projectRecord(value as Record<string, unknown>, budget, path, cuts, depth)
    }
    cuts.push(`${path || 'value'} omitted`)
    return DROPPED
}

function withNotice(value: unknown, notice: string): unknown {
    if (Array.isArray(value)) {
        return [...value, { [RESPONSE_BUDGET_KEY]: notice }]
    }
    return { [RESPONSE_BUDGET_KEY]: notice, ...(value as Record<string, unknown>) }
}

/** The projection counts JSON bytes, so its budget is scaled to the real serializer and then narrowed. */
export function fitValue(
    value: unknown,
    serialize: (value: unknown) => string,
    maxBytes: number,
    maxTokens: number
): { value: unknown; text: string } | undefined {
    if (typeof value !== 'object' || value === null) {
        return undefined
    }
    const fullBytes = byteLength(serialize(value))
    const ratio = fullBytes / Math.max(1, jsonBytes(value))
    let budget = Math.floor((maxBytes - NOTICE_RESERVE_BYTES) / ratio)
    for (let attempt = 0; attempt < MAX_FIT_ATTEMPTS && budget > MIN_STRING_KEEP_BYTES; attempt++) {
        const cuts: string[] = []
        const projected = withNotice(project(value, budget, '', cuts, 0), overflowNotice(fullBytes, maxTokens, cuts))
        const text = serialize(projected)
        const bytes = byteLength(text)
        if (bytes <= maxBytes) {
            return { value: projected, text }
        }
        budget = Math.floor((budget * maxBytes * 0.95) / bytes)
    }
    return undefined
}

function parseJsonText(text: string): unknown {
    const first = text.trimStart()[0]
    if (first !== '{' && first !== '[') {
        return undefined
    }
    try {
        return JSON.parse(text)
    } catch {
        return undefined
    }
}

export function boundText(
    text: string,
    maxTokens: number,
    source?: ResponseBodySource,
    maxBytes: number = maxResponseBytes(maxTokens)
): string {
    const fullBytes = byteLength(text)
    if (fullBytes <= maxBytes) {
        return text
    }
    if (source && typeof source.value !== 'string') {
        const fitted = fitValue(source.value, source.serialize, maxBytes, maxTokens)
        if (fitted) {
            return fitted.text
        }
    }
    const json = parseJsonText(text)
    if (json !== undefined) {
        const fitted = fitValue(json, (value) => JSON.stringify(value), maxBytes, maxTokens)
        if (fitted) {
            return fitted.text
        }
    }
    const notice = overflowNotice(fullBytes, maxTokens, [])
    const clipped = clipLines(text, maxBytes - byteLength(notice) - 2 - 64)
    return `${overflowNotice(fullBytes, maxTokens, [clipped.cut])}\n\n${clipped.text}`
}

export function toonResponseBody(value: unknown): ResponseBodySource {
    return { value, serialize: formatResponse }
}

export function jsonResponseBody(value: unknown): ResponseBodySource {
    return { value, serialize: (projected) => JSON.stringify(projected) }
}
