import type { AcpMessage, ToolCallContent, ToolCallLocation } from '../conversation/acp-types'
import type { TaskRun } from '../types'
import { TaskRunEnvironment, TaskRunStatus } from '../types'
import {
    type ChangedFileStatus,
    deriveChangedFiles,
    extractFileDiffFromToolCalls,
    parseRunOutputFiles,
} from './deriveChangedFiles'

function acpEvent(update: Record<string, unknown>): AcpMessage {
    return {
        type: 'acp_message',
        ts: 1,
        message: {
            jsonrpc: '2.0',
            method: 'session/update',
            params: { sessionId: 's1', update },
        },
    }
}

interface ToolCallEventOptions {
    kind?: string | null
    title?: string
    status?: string
    locations?: ToolCallLocation[]
    content?: ToolCallContent[]
    sessionUpdate?: 'tool_call' | 'tool_call_update'
}

function toolCallEvent(toolCallId: string, options: ToolCallEventOptions = {}): AcpMessage {
    const { sessionUpdate = 'tool_call', ...rest } = options
    return acpEvent({ sessionUpdate, toolCallId, ...rest })
}

function diff(path: string, newText: string, oldText: string | null = null): ToolCallContent {
    return { type: 'diff', path, oldText, newText }
}

function writeEvent(id: string, path: string, newText: string, oldText: string | null = null): AcpMessage {
    return toolCallEvent(id, {
        kind: 'write',
        status: 'completed',
        locations: [{ path }],
        content: [diff(path, newText, oldText)],
    })
}

function editEvent(id: string, path: string, oldText: string, newText: string): AcpMessage {
    return toolCallEvent(id, {
        kind: 'edit',
        status: 'completed',
        locations: [{ path }],
        content: [diff(path, newText, oldText)],
    })
}

function makeRun(output: Record<string, any> | null): TaskRun {
    return {
        id: 'run-1',
        task: 'task-1',
        stage: null,
        branch: null,
        status: TaskRunStatus.COMPLETED,
        environment: TaskRunEnvironment.CLOUD,
        log_url: null,
        error_message: null,
        output,
        state: {},
        artifacts: [],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        completed_at: null,
    }
}

describe('deriveChangedFiles', () => {
    describe('run.output priority', () => {
        it('uses run.output.files and ignores tool-call events', () => {
            const events = [writeEvent('t1', 'ignored.ts', 'from tool call')]
            const run = makeRun({
                files: [{ filename: 'src/app.ts', status: 'modified', additions: 5, deletions: 2 }],
            })

            expect(deriveChangedFiles(events, run)).toEqual([
                { path: 'src/app.ts', status: 'modified', linesAdded: 5, linesRemoved: 2 },
            ])
        })

        it('supports the pr_files key', () => {
            const run = makeRun({
                pr_files: [{ filename: 'README.md', status: 'added', additions: 10, deletions: 0 }],
            })

            expect(deriveChangedFiles([], run)).toEqual([
                { path: 'README.md', status: 'added', linesAdded: 10, linesRemoved: 0 },
            ])
        })

        it('supports the internal path/linesAdded shape', () => {
            const run = makeRun({
                files: [{ path: 'src/util.py', status: 'modified', linesAdded: 3, linesRemoved: 1 }],
            })

            expect(deriveChangedFiles([], run)).toEqual([
                { path: 'src/util.py', status: 'modified', linesAdded: 3, linesRemoved: 1 },
            ])
        })

        it.each<[string, ChangedFileStatus]>([
            ['added', 'added'],
            ['modified', 'modified'],
            ['removed', 'deleted'],
            ['deleted', 'deleted'],
            ['renamed', 'renamed'],
            ['changed', 'modified'],
            ['copied', 'added'],
            ['unknown_status', 'modified'],
        ])('maps run output status %s to %s', (rawStatus, expected) => {
            const run = makeRun({ files: [{ filename: 'a.ts', status: rawStatus }] })
            expect(deriveChangedFiles([], run)).toEqual([{ path: 'a.ts', status: expected }])
        })

        it('records renames with previous_filename and infers renamed status when status is missing', () => {
            const run = makeRun({
                files: [{ filename: 'src/new.ts', previous_filename: 'src/old.ts' }],
            })

            expect(deriveChangedFiles([], run)).toEqual([
                { path: 'src/new.ts', status: 'renamed', originalPath: 'src/old.ts' },
            ])
        })

        it('carries the git patch through', () => {
            const patch = '@@ -1 +1 @@\n-a\n+b'
            const run = makeRun({ files: [{ filename: 'a.ts', status: 'modified', patch }] })

            expect(deriveChangedFiles([], run)).toEqual([{ path: 'a.ts', status: 'modified', patch }])
        })

        it('skips entries without a path or filename', () => {
            const run = makeRun({
                files: [{ status: 'modified' }, null, 'garbage', { filename: 'kept.ts', status: 'added' }],
            })

            expect(deriveChangedFiles([], run)).toEqual([{ path: 'kept.ts', status: 'added' }])
        })

        it('falls back to tool calls when output.files is empty or all entries are invalid', () => {
            const events = [writeEvent('t1', 'src/fallback.ts', 'one\ntwo')]

            expect(deriveChangedFiles(events, makeRun({ files: [] }))).toEqual([
                { path: 'src/fallback.ts', status: 'added', linesAdded: 2, linesRemoved: 0 },
            ])
            expect(deriveChangedFiles(events, makeRun({ files: [{ status: 'modified' }] }))).toEqual([
                { path: 'src/fallback.ts', status: 'added', linesAdded: 2, linesRemoved: 0 },
            ])
        })

        it('falls back to tool calls when output has no file list', () => {
            const events = [writeEvent('t1', 'src/fallback.ts', 'one')]

            expect(deriveChangedFiles(events, makeRun({ pr_url: 'https://github.com/o/r/pull/1' }))).toEqual([
                { path: 'src/fallback.ts', status: 'added', linesAdded: 1, linesRemoved: 0 },
            ])
            expect(deriveChangedFiles(events, makeRun({ files: 'not-an-array' }))).toEqual([
                { path: 'src/fallback.ts', status: 'added', linesAdded: 1, linesRemoved: 0 },
            ])
            expect(deriveChangedFiles(events, null)).toEqual([
                { path: 'src/fallback.ts', status: 'added', linesAdded: 1, linesRemoved: 0 },
            ])
        })
    })

    describe('tool-call fallback', () => {
        it('returns an empty list for no events', () => {
            expect(deriveChangedFiles([])).toEqual([])
        })

        it('marks a write without oldText as added with full line count', () => {
            const events = [writeEvent('t1', 'src/new.ts', 'a\nb\nc')]

            expect(deriveChangedFiles(events)).toEqual([
                { path: 'src/new.ts', status: 'added', linesAdded: 3, linesRemoved: 0 },
            ])
        })

        it('marks a write with oldText as modified with computed stats', () => {
            const events = [writeEvent('t1', 'src/app.ts', 'a\nc', 'a\nb')]

            expect(deriveChangedFiles(events)).toEqual([
                { path: 'src/app.ts', status: 'modified', linesAdded: 1, linesRemoved: 1 },
            ])
        })

        it('marks an edit as modified', () => {
            const events = [editEvent('t1', 'src/app.ts', 'a', 'a\nb')]

            expect(deriveChangedFiles(events)).toEqual([
                { path: 'src/app.ts', status: 'modified', linesAdded: 1, linesRemoved: 0 },
            ])
        })

        it('accumulates multiple edits per path into one entry with cumulative stats', () => {
            const events = [
                editEvent('t1', 'src/app.ts', 'a', 'a\nb'),
                editEvent('t2', 'src/app.ts', 'a\nb', 'a\nb\nc'),
            ]

            expect(deriveChangedFiles(events)).toEqual([
                { path: 'src/app.ts', status: 'modified', linesAdded: 2, linesRemoved: 0 },
            ])
        })

        it('keeps added status when a created file is subsequently edited', () => {
            const events = [writeEvent('t1', 'src/new.ts', 'a'), editEvent('t2', 'src/new.ts', 'a', 'a\nb')]

            expect(deriveChangedFiles(events)).toEqual([
                { path: 'src/new.ts', status: 'added', linesAdded: 2, linesRemoved: 0 },
            ])
        })

        it('merges tool_call and tool_call_update for the same toolCallId', () => {
            const events = [
                toolCallEvent('t1', { kind: 'edit', status: 'in_progress', locations: [{ path: 'src/app.ts' }] }),
                toolCallEvent('t1', {
                    sessionUpdate: 'tool_call_update',
                    status: 'completed',
                    content: [diff('src/app.ts', 'a\nb', 'a')],
                }),
            ]

            expect(deriveChangedFiles(events)).toEqual([
                { path: 'src/app.ts', status: 'modified', linesAdded: 1, linesRemoved: 0 },
            ])
        })

        it('ignores failed tool calls', () => {
            const events = [
                toolCallEvent('t1', {
                    kind: 'write',
                    status: 'failed',
                    content: [diff('src/failed.ts', 'nope')],
                }),
            ]

            expect(deriveChangedFiles(events)).toEqual([])
        })

        it('ignores non-mutating tool kinds', () => {
            const events = [
                toolCallEvent('t1', { kind: 'read', status: 'completed', locations: [{ path: 'src/app.ts' }] }),
                toolCallEvent('t2', { kind: 'execute', status: 'completed', title: 'Run tests' }),
            ]

            expect(deriveChangedFiles(events)).toEqual([])
        })

        it('marks deletes as deleted without stats', () => {
            const events = [
                toolCallEvent('t1', { kind: 'delete', status: 'completed', locations: [{ path: 'src/old.ts' }] }),
            ]

            expect(deriveChangedFiles(events)).toEqual([{ path: 'src/old.ts', status: 'deleted' }])
        })

        it('marks moves as renamed with originalPath from the source location', () => {
            const events = [
                toolCallEvent('t1', {
                    kind: 'move',
                    status: 'completed',
                    locations: [{ path: 'src/old.ts' }, { path: 'src/new.ts' }],
                }),
            ]

            expect(deriveChangedFiles(events)).toEqual([
                { path: 'src/new.ts', status: 'renamed', originalPath: 'src/old.ts' },
            ])
        })

        it('folds an edit followed by a move into a single renamed entry', () => {
            const events = [
                editEvent('t1', 'src/old.ts', 'a', 'a\nb'),
                toolCallEvent('t2', {
                    kind: 'move',
                    status: 'completed',
                    locations: [{ path: 'src/old.ts' }, { path: 'src/new.ts' }],
                }),
            ]

            expect(deriveChangedFiles(events)).toEqual([
                { path: 'src/new.ts', status: 'renamed', originalPath: 'src/old.ts', linesAdded: 1, linesRemoved: 0 },
            ])
        })

        it('infers the kind from the title when kind is missing', () => {
            const events = [
                toolCallEvent('t1', {
                    title: 'Write src/new.ts',
                    status: 'completed',
                    content: [diff('src/new.ts', 'a')],
                }),
                toolCallEvent('t2', {
                    title: 'Delete src/old.ts',
                    status: 'completed',
                    locations: [{ path: 'src/old.ts' }],
                }),
            ]

            expect(deriveChangedFiles(events)).toEqual([
                { path: 'src/new.ts', status: 'added', linesAdded: 1, linesRemoved: 0 },
                { path: 'src/old.ts', status: 'deleted' },
            ])
        })

        it('skips agent plan files', () => {
            const events = [writeEvent('t1', '/repo/.claude/plans/plan.md', 'plan')]

            expect(deriveChangedFiles(events)).toEqual([])
        })

        it('orders files by last touch', () => {
            const events = [
                writeEvent('t1', 'a.ts', 'a'),
                writeEvent('t2', 'b.ts', 'b'),
                editEvent('t3', 'a.ts', 'a', 'a\nx'),
            ]

            expect(deriveChangedFiles(events).map((file) => file.path)).toEqual(['b.ts', 'a.ts'])
        })

        it('treats a delete followed by a rewrite as modified', () => {
            const events = [
                toolCallEvent('t1', { kind: 'delete', status: 'completed', locations: [{ path: 'a.ts' }] }),
                writeEvent('t2', 'a.ts', 'a'),
            ]

            expect(deriveChangedFiles(events)).toEqual([
                { path: 'a.ts', status: 'modified', linesAdded: 1, linesRemoved: 0 },
            ])
        })

        it('uses the diff path over the location path when both are present', () => {
            const events = [
                toolCallEvent('t1', {
                    kind: 'edit',
                    status: 'completed',
                    locations: [{ path: '/abs/repo/src/app.ts' }],
                    content: [diff('src/app.ts', 'a\nb', 'a')],
                }),
            ]

            expect(deriveChangedFiles(events).map((file) => file.path)).toEqual(['src/app.ts'])
        })
    })

    describe('extractFileDiffFromToolCalls', () => {
        it('returns null when no tool call touched the path', () => {
            const events = [writeEvent('t1', 'other.ts', 'a')]

            expect(extractFileDiffFromToolCalls(events, 'src/app.ts')).toBeNull()
        })

        it('returns oldText null and the written content for a new file', () => {
            const events = [writeEvent('t1', 'src/new.ts', 'a\nb')]

            expect(extractFileDiffFromToolCalls(events, 'src/new.ts')).toEqual({ oldText: null, newText: 'a\nb' })
        })

        it('returns the first oldText and last newText across multiple calls', () => {
            const events = [
                editEvent('t1', 'src/app.ts', 'v1', 'v2'),
                editEvent('t2', 'src/app.ts', 'v2', 'v3'),
                editEvent('t3', 'src/app.ts', 'v3', 'v4'),
            ]

            expect(extractFileDiffFromToolCalls(events, 'src/app.ts')).toEqual({ oldText: 'v1', newText: 'v4' })
        })

        it('matches absolute event paths against relative queries and vice versa', () => {
            const events = [editEvent('t1', '/repo/src/app.ts', 'old', 'new')]

            expect(extractFileDiffFromToolCalls(events, 'src/app.ts')).toEqual({ oldText: 'old', newText: 'new' })

            const relativeEvents = [editEvent('t1', 'src/app.ts', 'old', 'new')]
            expect(extractFileDiffFromToolCalls(relativeEvents, '/repo/src/app.ts')).toEqual({
                oldText: 'old',
                newText: 'new',
            })
        })

        it('does not match different files with the same suffix-free name', () => {
            const events = [editEvent('t1', 'src/app.ts', 'old', 'new')]

            expect(extractFileDiffFromToolCalls(events, 'other/app.ts')).toBeNull()
        })

        it('skips failed tool calls', () => {
            const events = [
                toolCallEvent('t1', {
                    kind: 'edit',
                    status: 'failed',
                    content: [diff('src/app.ts', 'bad', 'old')],
                }),
                editEvent('t2', 'src/app.ts', 'old', 'good'),
            ]

            expect(extractFileDiffFromToolCalls(events, 'src/app.ts')).toEqual({ oldText: 'old', newText: 'good' })
        })

        it('returns newText null when the last call was a delete without diff content', () => {
            const events = [
                writeEvent('t1', 'src/app.ts', 'content'),
                toolCallEvent('t2', { kind: 'delete', status: 'completed', locations: [{ path: 'src/app.ts' }] }),
            ]

            expect(extractFileDiffFromToolCalls(events, 'src/app.ts')).toEqual({ oldText: null, newText: null })
        })
    })

    describe('parseRunOutputFiles', () => {
        it('returns null for runs without output', () => {
            expect(parseRunOutputFiles(null)).toBeNull()
            expect(parseRunOutputFiles(makeRun(null))).toBeNull()
            expect(parseRunOutputFiles(makeRun({}))).toBeNull()
        })

        it('prefers files over pr_files when both are present', () => {
            const run = makeRun({
                files: [{ filename: 'from-files.ts', status: 'modified' }],
                pr_files: [{ filename: 'from-pr.ts', status: 'modified' }],
            })

            expect(parseRunOutputFiles(run)).toEqual([{ path: 'from-files.ts', status: 'modified' }])
        })

        it('drops originalPath when it equals the path', () => {
            const run = makeRun({
                files: [{ filename: 'same.ts', previous_filename: 'same.ts', status: 'modified' }],
            })

            expect(parseRunOutputFiles(run)).toEqual([{ path: 'same.ts', status: 'modified' }])
        })

        it('ignores non-finite or non-numeric line counts', () => {
            const run = makeRun({
                files: [{ filename: 'a.ts', status: 'modified', additions: 'lots', deletions: NaN }],
            })

            expect(parseRunOutputFiles(run)).toEqual([{ path: 'a.ts', status: 'modified' }])
        })
    })
})
