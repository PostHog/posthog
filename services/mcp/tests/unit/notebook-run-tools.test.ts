import { afterEach, describe, expect, it, vi } from 'vitest'

import { runNotebookHandler } from '@/tools/notebooks/runNotebook'
import { runNotebookStatusHandler } from '@/tools/notebooks/runNotebookStatus'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

const MARKDOWN =
    '# Report\n\n' +
    '<SQLV2 nodeId="s1" code="select 1" returnVariable="df" />\n\n' +
    '<PythonV2 nodeId="p1" code="out = df.head()" returnVariable="out" />\n'

interface MockState {
    markdown: string
    version: number
    start: Record<string, unknown>
    runStatuses: any[]
    cellResults: Record<string, any>
    saveBodies: any[]
    startBodies: any[]
}

function markdownContent(markdown: string): Record<string, unknown> {
    return {
        type: 'doc',
        content: [{ type: 'ph-markdown-notebook', attrs: { nodeId: 'markdown-notebook-v2', markdown } }],
    }
}

function makeState(overrides: Partial<MockState> = {}): MockState {
    return {
        markdown: MARKDOWN,
        version: 3,
        start: { run_id: 'nbrun-1', cell_count: 2, starts_sandbox: true, sandbox_hourly_price: 0.42 },
        runStatuses: [],
        cellResults: {},
        saveBodies: [],
        startBodies: [],
        ...overrides,
    }
}

function createMockContext(state: MockState): Context {
    const request = vi.fn(async (opts: { method: string; path?: string; body?: any }) => {
        const path = opts.path ?? ''
        if (opts.method === 'POST' && path.endsWith('/runs/')) {
            state.startBodies.push(opts.body)
            return state.start
        }
        if (opts.method === 'GET' && /\/sql_v2\/runs\//.test(path)) {
            const runId = path.split('/sql_v2/runs/')[1]!.replace(/\/$/, '')
            const result = state.cellResults[runId]
            if (!result) {
                throw new Error(`No queued cell result for ${runId}`)
            }
            return result
        }
        if (opts.method === 'GET' && /\/runs\//.test(path)) {
            const next = state.runStatuses.length > 1 ? state.runStatuses.shift() : state.runStatuses[0]
            if (!next) {
                throw new Error('No queued run status')
            }
            return next
        }
        if (opts.method === 'POST' && path.endsWith('/collab/markdown_save/')) {
            state.saveBodies.push(opts.body)
            state.markdown = opts.body.content.content[0].attrs.markdown
            state.version += 1
            return { short_id: 'aBcD1234', content: opts.body.content, version: state.version, variables: [] }
        }
        if (opts.method === 'GET') {
            return {
                short_id: 'aBcD1234',
                content: markdownContent(state.markdown),
                version: state.version,
                variables: [],
            }
        }
        throw new Error(`Unexpected request: ${opts.method} ${path}`)
    })
    return {
        api: { request, getProjectBaseUrl: (id: string) => `https://us.posthog.com/project/${id}` } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test',
        trackEvent: async () => {},
    } as unknown as Context
}

function runStatus(status: string, cells: any[], extra: Record<string, unknown> = {}): any {
    return {
        run_id: 'nbrun-1',
        status,
        trigger: 'mcp',
        variables: [],
        current_node_id: null,
        current_index: 0,
        failed_node_id: null,
        error: null,
        cells,
        created_at: '2026-01-01T00:00:00Z',
        finished_at: null,
        ...extra,
    }
}

function cell(nodeId: string, dataframe: string, status: string | null, runId: string | null = null): any {
    return { node_id: nodeId, cell_type: 'sql', dataframe_name: dataframe, run_id: runId, status, error: null }
}

function doneResult(rows: number): any {
    return {
        status: 'done',
        result: {
            status: 'ok',
            columns: ['x'],
            types: [['x', 'Int64']],
            row_count: rows,
            first_page: [[1]],
            has_more: false,
            stdout: '',
            stderr: '',
            media: [{ mime_type: 'image/png', data: 'aGVsbG8=' }],
        },
        error: null,
    }
}

const unwrap = (result: any): any => result.data ?? result

describe('notebook run tools', () => {
    afterEach(() => {
        vi.useRealTimers()
    })

    it('starts a run and reports the sandbox price the user has to be told', async () => {
        const state = makeState({
            runStatuses: [runStatus('done', [cell('s1', 'df', 'done', 'r1'), cell('p1', 'out', 'done', 'r2')])],
            cellResults: { r1: doneResult(1), r2: doneResult(2) },
        })
        const context = createMockContext(state)

        const result = unwrap(await runNotebookHandler(context, { notebook_id: 'aBcD1234', wait: true } as any))

        expect(state.startBodies).toEqual([{}])
        expect(result.status).toBe('done')
        expect(result.cell_count).toBe(2)
        expect(result.completed_count).toBe(2)
        expect(result.starts_sandbox).toBe(true)
        expect(result.sandbox_hourly_price).toBe(0.42)
    })

    it('writes every finished cell into the document in one save', async () => {
        // A save per cell would bump the notebook version once per cell and show every
        // collaborator a burst of edits.
        const state = makeState({
            runStatuses: [runStatus('done', [cell('s1', 'df', 'done', 'r1'), cell('p1', 'out', 'done', 'r2')])],
            cellResults: { r1: doneResult(1), r2: doneResult(2) },
        })
        const context = createMockContext(state)

        await runNotebookHandler(context, { notebook_id: 'aBcD1234', wait: true } as any)

        expect(state.saveBodies).toHaveLength(1)
        expect(state.markdown).toContain('runId="r1"')
        expect(state.markdown).toContain('runId="r2"')
        expect(state.markdown).toContain('"row_count":1')
        expect(state.markdown).toContain('"row_count":2')
    })

    it('keeps base64 media out of the model result', async () => {
        const state = makeState({
            runStatuses: [runStatus('done', [cell('s1', 'df', 'done', 'r1')])],
            cellResults: { r1: doneResult(1) },
        })
        const context = createMockContext(state)

        const result = unwrap(await runNotebookHandler(context, { notebook_id: 'aBcD1234', wait: true } as any))

        expect(result.cells[0].run.media).toEqual([{ mime_type: 'image/png' }])
        expect(JSON.stringify(result)).not.toContain('aGVsbG8=')
    })

    it('names the cell that stopped the run', async () => {
        const failed = runStatus(
            'failed',
            [
                { ...cell('s1', 'df', 'done', 'r1') },
                { ...cell('p1', 'out', 'failed', 'r2'), error: 'name df is not defined' },
            ],
            { failed_node_id: 'p1', error: 'name df is not defined' }
        )
        const state = makeState({
            runStatuses: [failed],
            cellResults: { r1: doneResult(1), r2: { status: 'failed', result: null, error: 'name df is not defined' } },
        })
        const context = createMockContext(state)

        const result = unwrap(await runNotebookHandler(context, { notebook_id: 'aBcD1234', wait: true } as any))

        expect(result.status).toBe('failed')
        expect(result.failed_cell).toEqual({
            node_id: 'p1',
            dataframe_name: 'out',
            error: 'name df is not defined',
        })
    })

    it('returns running with a hint when the wait budget ends first', async () => {
        // The agent has to keep following the run rather than start a second one.
        const state = makeState({
            runStatuses: [runStatus('running', [cell('s1', 'df', 'running', 'r1'), cell('p1', 'out', null)])],
            cellResults: {},
        })
        const context = createMockContext(state)

        const result = unwrap(await runNotebookHandler(context, { notebook_id: 'aBcD1234', wait: false } as any))

        expect(result.status).toBe('running')
        expect(result.hint).toContain('notebooks-run-status')
        expect(state.saveBodies).toHaveLength(0)
    })

    it('follows a run that finishes on a later poll and writes only the new results', async () => {
        vi.useFakeTimers()
        const state = makeState({
            runStatuses: [
                runStatus('running', [cell('s1', 'df', 'done', 'r1'), cell('p1', 'out', 'running', 'r2')]),
                runStatus('done', [cell('s1', 'df', 'done', 'r1'), cell('p1', 'out', 'done', 'r2')]),
            ],
            cellResults: { r1: doneResult(1), r2: doneResult(2) },
        })
        const context = createMockContext(state)

        const pending = runNotebookStatusHandler(context, {
            notebook_id: 'aBcD1234',
            run_id: 'nbrun-1',
        } as any)
        await vi.advanceTimersByTimeAsync(5_000)
        const result = unwrap(await pending)

        expect(result.status).toBe('done')
        // One save for the cell that finished first, one for the cell that finished after it.
        expect(state.saveBodies).toHaveLength(2)
        expect(state.markdown).toContain('runId="r2"')
    })

    it('refuses a repeated variable name before it starts anything', async () => {
        const state = makeState({ runStatuses: [runStatus('done', [])] })
        const context = createMockContext(state)

        await expect(
            runNotebookHandler(context, {
                notebook_id: 'aBcD1234',
                wait: true,
                variables: [
                    { name: 'country', type: 'string', value: 'US' },
                    { name: 'country', type: 'string', value: 'GB' },
                ],
            } as any)
        ).rejects.toThrow('Repeated: country')
        expect(state.startBodies).toHaveLength(0)
    })

    it('both tools are gated on the revamped notebooks flag and need write access', () => {
        for (const name of ['notebooks-run', 'notebooks-run-status']) {
            const definition = getToolDefinition(name)
            expect(definition.feature_flag).toBe('revamped-py-notebooks')
            expect(definition.required_scopes).toContain('notebook:write')
        }
    })
})
