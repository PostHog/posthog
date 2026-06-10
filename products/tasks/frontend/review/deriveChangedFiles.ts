/**
 * Pure helpers that derive the set of changed files (and their diffs) for a
 * cloud task run. Ported from PostHog Code's `cloudToolChanges.ts`, adapted
 * for the web: there is no git/PR file API here, so files come either from
 * `run.output` (when the backend attaches PR file metadata) or are folded
 * from write/edit/delete/move tool-call `DiffContent` in the ACP event stream.
 */
import type { AcpMessage, ToolCallContent, ToolCallLocation } from '../conversation/acp-types'
import { isJsonRpcNotification } from '../conversation/acp-types'
import type { TaskRun } from '../types'

export type ChangedFileStatus = 'added' | 'modified' | 'deleted' | 'renamed'

export interface ChangedFile {
    path: string
    status: ChangedFileStatus
    /** For renames: the old path. */
    originalPath?: string
    linesAdded?: number
    linesRemoved?: number
    /** Unified git diff patch, when supplied by run.output (GitHub PR file shape). */
    patch?: string
}

export interface FileDiffText {
    oldText: string | null
    newText: string | null
}

export interface ParsedToolCall {
    toolCallId: string
    kind?: string | null
    title?: string
    status?: string | null
    locations?: ToolCallLocation[]
    content?: ToolCallContent[]
}

const WRITE_KINDS = new Set(['write', 'edit', 'delete', 'move'])

/** Match file paths that may differ in format (absolute vs relative). */
function pathsMatch(a: string | undefined, b: string): boolean {
    if (!a) {
        return false
    }
    if (a === b) {
        return true
    }
    return a.endsWith(`/${b}`) || b.endsWith(`/${a}`)
}

function inferKind(kind: string | null | undefined, title: string | undefined): string | null {
    if (kind) {
        return kind
    }
    if (!title) {
        return null
    }
    const normalized = title.toLowerCase()
    if (normalized.startsWith('write')) {
        return 'write'
    }
    if (normalized.startsWith('edit')) {
        return 'edit'
    }
    if (normalized.startsWith('delete')) {
        return 'delete'
    }
    if (normalized.startsWith('move') || normalized.startsWith('rename')) {
        return 'move'
    }
    return null
}

function mergeToolCall(existing: ParsedToolCall | undefined, patch: Partial<ParsedToolCall>): ParsedToolCall {
    return {
        toolCallId: patch.toolCallId ?? existing?.toolCallId ?? '',
        kind: patch.kind ?? existing?.kind,
        title: patch.title ?? existing?.title,
        status: patch.status ?? existing?.status,
        locations: patch.locations && patch.locations.length > 0 ? patch.locations : existing?.locations,
        content: patch.content && patch.content.length > 0 ? patch.content : existing?.content,
    }
}

function getDiffContent(
    content: ToolCallContent[] | undefined
): Extract<ToolCallContent, { type: 'diff' }> | undefined {
    return content?.find((item): item is Extract<ToolCallContent, { type: 'diff' }> => item.type === 'diff')
}

/**
 * Bag-of-lines diff stats. Recomputed for every changed file whenever the
 * event stream updates, so it trades accuracy (no ordering) for speed.
 */
function computeDiffStats(
    oldText: string | null | undefined,
    newText: string | null | undefined
): { added: number; removed: number } {
    if (!oldText && !newText) {
        return { added: 0, removed: 0 }
    }

    const oldLines = oldText ? oldText.split('\n') : []
    const newLines = newText ? newText.split('\n') : []

    if (!oldText) {
        return { added: newLines.length, removed: 0 }
    }

    const oldCounts = new Map<string, number>()
    for (const line of oldLines) {
        oldCounts.set(line, (oldCounts.get(line) ?? 0) + 1)
    }

    const newCounts = new Map<string, number>()
    for (const line of newLines) {
        newCounts.set(line, (newCounts.get(line) ?? 0) + 1)
    }

    let added = 0
    let removed = 0
    for (const [line, count] of newCounts) {
        const oldCount = oldCounts.get(line) ?? 0
        if (count > oldCount) {
            added += count - oldCount
        }
    }
    for (const [line, count] of oldCounts) {
        const newCount = newCounts.get(line) ?? 0
        if (count > newCount) {
            removed += count - newCount
        }
    }

    return { added, removed }
}

/** Single-pass extraction of tool calls (merged across tool_call/tool_call_update) from the event stream. */
export function buildToolCallSummary(events: AcpMessage[]): Map<string, ParsedToolCall> {
    const toolCalls = new Map<string, ParsedToolCall>()

    for (const event of events) {
        const message = event.message
        if (!isJsonRpcNotification(message) || message.method !== 'session/update') {
            continue
        }

        const params = message.params as { update?: Record<string, unknown> } | undefined
        const update = params?.update
        if (!update || typeof update !== 'object') {
            continue
        }

        const sessionUpdate = update.sessionUpdate
        if (sessionUpdate !== 'tool_call' && sessionUpdate !== 'tool_call_update') {
            continue
        }

        const toolCallId = typeof update.toolCallId === 'string' ? update.toolCallId : undefined
        if (!toolCallId) {
            continue
        }

        const patch: Partial<ParsedToolCall> = {
            toolCallId,
            kind: typeof update.kind === 'string' ? update.kind : null,
            title: typeof update.title === 'string' ? update.title : undefined,
            status: typeof update.status === 'string' ? update.status : null,
            locations: Array.isArray(update.locations) ? (update.locations as ToolCallLocation[]) : undefined,
            content: Array.isArray(update.content) ? (update.content as ToolCallContent[]) : undefined,
        }

        toolCalls.set(toolCallId, mergeToolCall(toolCalls.get(toolCallId), patch))
    }

    return toolCalls
}

interface PathFold {
    path: string
    originalPath?: string
    firstOldText: string | null
    lastNewText: string | null
    hasDiff: boolean
    touched: boolean
    createdInSession: boolean
    deleted: boolean
    renamed: boolean
}

function reinsertFold(folds: Map<string, PathFold>, path: string, seed?: PathFold): PathFold {
    const existing = seed ?? folds.get(path)
    // Delete and re-insert so the last-touched path appears at the end of iteration order
    folds.delete(path)
    const fold: PathFold = existing
        ? { ...existing, path }
        : {
              path,
              firstOldText: null,
              lastNewText: null,
              hasDiff: false,
              touched: false,
              createdInSession: false,
              deleted: false,
              renamed: false,
          }
    folds.set(path, fold)
    return fold
}

function applyDiff(fold: PathFold, diff: Extract<ToolCallContent, { type: 'diff' }> | undefined): void {
    if (!diff) {
        return
    }
    if (!fold.hasDiff) {
        fold.firstOldText = diff.oldText ?? null
    }
    fold.lastNewText = diff.newText ?? null
    fold.hasDiff = true
}

/**
 * Fold write/edit/delete/move tool calls into per-path changed files.
 * Last write wins per path; stats are cumulative (first oldText vs last newText).
 */
export function extractChangedFilesFromToolCalls(toolCalls: Map<string, ParsedToolCall>): ChangedFile[] {
    const folds = new Map<string, PathFold>()

    for (const toolCall of toolCalls.values()) {
        if (toolCall.status === 'failed') {
            continue
        }

        const kind = inferKind(toolCall.kind, toolCall.title)
        if (!kind || !WRITE_KINDS.has(kind)) {
            continue
        }

        const diff = getDiffContent(toolCall.content)
        const sourcePath = toolCall.locations?.[0]?.path
        const destinationPath = toolCall.locations?.[1]?.path
        const path = diff?.path ?? (kind === 'move' ? destinationPath : sourcePath)
        if (!path || path.includes('.claude/plans/')) {
            continue
        }

        if (kind === 'move') {
            // Carry any accumulated state from the source path over to the destination
            const sourceFold = sourcePath && sourcePath !== path ? folds.get(sourcePath) : undefined
            if (sourcePath && sourcePath !== path) {
                folds.delete(sourcePath)
            }
            const fold = reinsertFold(folds, path, sourceFold)
            fold.renamed = true
            fold.deleted = false
            fold.originalPath = fold.originalPath ?? sourcePath
            applyDiff(fold, diff)
            fold.touched = true
            continue
        }

        const fold = reinsertFold(folds, path)
        if (kind === 'delete') {
            fold.deleted = true
            fold.touched = true
            continue
        }

        // write / edit
        if (!fold.touched) {
            fold.createdInSession = kind === 'write' && diff?.oldText == null
        }
        fold.deleted = false
        applyDiff(fold, diff)
        fold.touched = true
    }

    const files: ChangedFile[] = []
    for (const fold of folds.values()) {
        const status: ChangedFileStatus = fold.deleted
            ? 'deleted'
            : fold.renamed
              ? 'renamed'
              : fold.createdInSession
                ? 'added'
                : 'modified'
        const file: ChangedFile = { path: fold.path, status }
        if (fold.originalPath && fold.originalPath !== fold.path) {
            file.originalPath = fold.originalPath
        }
        if (fold.hasDiff && !fold.deleted) {
            const stats = computeDiffStats(fold.firstOldText, fold.lastNewText)
            file.linesAdded = stats.added
            file.linesRemoved = stats.removed
        }
        files.push(file)
    }
    return files
}

// GitHub PR file statuses → our statuses. Unknown statuses fall back to 'modified'.
const RUN_OUTPUT_STATUS_MAP: Record<string, ChangedFileStatus> = {
    added: 'added',
    untracked: 'added',
    copied: 'added',
    removed: 'deleted',
    deleted: 'deleted',
    modified: 'modified',
    changed: 'modified',
    unchanged: 'modified',
    renamed: 'renamed',
}

function firstString(...values: unknown[]): string | undefined {
    for (const value of values) {
        if (typeof value === 'string' && value.length > 0) {
            return value
        }
    }
    return undefined
}

function firstNumber(...values: unknown[]): number | undefined {
    for (const value of values) {
        if (typeof value === 'number' && Number.isFinite(value)) {
            return value
        }
    }
    return undefined
}

function parseRunOutputFile(entry: unknown): ChangedFile | null {
    if (!entry || typeof entry !== 'object') {
        return null
    }
    const record = entry as Record<string, unknown>

    // Supports both internal `{path, linesAdded, ...}` and GitHub PR `{filename, additions, ...}` shapes
    const path = firstString(record.path, record.filename)
    if (!path) {
        return null
    }

    const originalPath = firstString(
        record.originalPath,
        record.original_path,
        record.previousFilename,
        record.previous_filename
    )
    const statusRaw = typeof record.status === 'string' ? record.status.toLowerCase() : undefined
    const status: ChangedFileStatus =
        (statusRaw ? RUN_OUTPUT_STATUS_MAP[statusRaw] : undefined) ?? (originalPath ? 'renamed' : 'modified')

    const file: ChangedFile = { path, status }
    if (originalPath && originalPath !== path) {
        file.originalPath = originalPath
    }
    const linesAdded = firstNumber(record.linesAdded, record.lines_added, record.additions)
    if (linesAdded !== undefined) {
        file.linesAdded = linesAdded
    }
    const linesRemoved = firstNumber(record.linesRemoved, record.lines_removed, record.deletions)
    if (linesRemoved !== undefined) {
        file.linesRemoved = linesRemoved
    }
    if (typeof record.patch === 'string' && record.patch.length > 0) {
        file.patch = record.patch
    }
    return file
}

/**
 * Extract changed-file metadata from `run.output`, when the backend attached
 * it. `TaskRun.output` is untyped, so every field is runtime-guarded.
 * Returns null when no usable file list is present (caller falls back to tool calls).
 */
export function parseRunOutputFiles(run: TaskRun | null | undefined): ChangedFile[] | null {
    const output = run?.output
    if (!output || typeof output !== 'object') {
        return null
    }
    const raw = (output as Record<string, unknown>).files ?? (output as Record<string, unknown>).pr_files
    if (!Array.isArray(raw)) {
        return null
    }
    const files: ChangedFile[] = []
    for (const entry of raw) {
        const file = parseRunOutputFile(entry)
        if (file) {
            files.push(file)
        }
    }
    return files.length > 0 ? files : null
}

/**
 * Derive the changed files for a run. Priority: file metadata carried on
 * `run.output` (`files` / `pr_files`); fallback: files folded from tool-call
 * DiffContent in the event stream.
 */
export function deriveChangedFiles(events: AcpMessage[], run?: TaskRun | null): ChangedFile[] {
    const fromRun = parseRunOutputFiles(run)
    if (fromRun) {
        return fromRun
    }
    return extractChangedFilesFromToolCalls(buildToolCallSummary(events))
}

/**
 * Cumulative old/new text for a file across all of its tool calls:
 * oldText from the *first* matching call, newText from the *last*.
 */
export function extractFileDiff(toolCalls: Map<string, ParsedToolCall>, filePath: string): FileDiffText | null {
    let firstOldText: string | null | undefined
    let lastNewText: string | null | undefined
    let found = false

    for (const toolCall of toolCalls.values()) {
        if (toolCall.status === 'failed') {
            continue
        }

        const kind = inferKind(toolCall.kind, toolCall.title)
        if (!kind || !WRITE_KINDS.has(kind)) {
            continue
        }

        const diff = getDiffContent(toolCall.content)
        const sourcePath = toolCall.locations?.[0]?.path
        const destinationPath = toolCall.locations?.[1]?.path
        const path = diff?.path ?? (kind === 'move' ? destinationPath : sourcePath)
        if (!pathsMatch(path, filePath)) {
            continue
        }

        if (!found) {
            firstOldText = diff?.oldText ?? null
            found = true
        }
        lastNewText = diff?.newText ?? null
    }

    if (!found) {
        return null
    }

    return { oldText: firstOldText ?? null, newText: lastNewText ?? null }
}

/** Convenience wrapper over `extractFileDiff` for callers that hold raw events. */
export function extractFileDiffFromToolCalls(events: AcpMessage[], filePath: string): FileDiffText | null {
    return extractFileDiff(buildToolCallSummary(events), filePath)
}
