import { afterEach, describe, expect, it, vi } from 'vitest'

import { addCellHandler } from '@/tools/notebooks/addCell'
import { createMarkdownHandler } from '@/tools/notebooks/createMarkdown'
import { deleteCellHandler } from '@/tools/notebooks/deleteCell'
import { updateCellHandler } from '@/tools/notebooks/updateCell'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, type Context } from '@/tools/types'

type AddCellParams = Parameters<typeof addCellHandler>[1]

interface MockState {
    markdown: string
    version: number
    saveBodies: any[]
    runBodies: any[]
    runStatusResponses: any[]
    createBodies: any[]
}

function markdownContent(markdown: string): Record<string, unknown> {
    return {
        type: 'doc',
        content: [{ type: 'ph-markdown-notebook', attrs: { nodeId: 'markdown-notebook-v2', markdown } }],
    }
}

function createMockContext(state: MockState): Context {
    const request = vi.fn(async (opts: { method: string; path?: string; body?: any }) => {
        const path = opts.path ?? ''
        if (opts.method === 'GET' && /\/sql_v2\/runs\//.test(path)) {
            const next = state.runStatusResponses.shift()
            if (!next) {
                throw new Error('No queued run status response')
            }
            return next
        }
        if (opts.method === 'GET') {
            return { short_id: 'aBcD1234', content: markdownContent(state.markdown), version: state.version }
        }
        if (opts.method === 'POST' && path.endsWith('/sql_v2/run/')) {
            state.runBodies.push(opts.body)
            return { run_id: 'run-1' }
        }
        if (opts.method === 'POST' && path.endsWith('/collab/markdown_save/')) {
            state.saveBodies.push(opts.body)
            state.markdown = opts.body.content.content[0].attrs.markdown
            state.version += 1
            return { short_id: 'aBcD1234', content: opts.body.content, version: state.version }
        }
        if (opts.method === 'POST' && path.endsWith('/notebooks/')) {
            state.createBodies.push(opts.body)
            return { short_id: 'nEw12345', content: opts.body.content, version: 0 }
        }
        throw new Error(`Unexpected request: ${opts.method} ${path}`)
    })
    return {
        api: {
            request,
            getProjectBaseUrl: (projectId: string) => `https://us.posthog.com/project/${projectId}`,
        } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test',
        trackEvent: async () => {},
    } as unknown as Context
}

function makeState(markdown: string): MockState {
    return { markdown, version: 3, saveBodies: [], runBodies: [], runStatusResponses: [], createBodies: [] }
}

const DONE_STATUS = {
    status: 'done',
    result: {
        status: 'ok',
        columns: ['x'],
        types: [['x', 'Int64']],
        row_count: 1,
        first_page: [[1]],
        has_more: false,
        stdout: 'hello',
        stderr: '',
        media: [{ mime_type: 'image/png', data: 'aGVsbG8=' }],
    },
    error: null,
}

describe('notebook cell tools', () => {
    afterEach(() => {
        vi.useRealTimers()
    })

    it('add sql cell inserts the tag, runs with sibling refs, and writes the result back', async () => {
        const state = makeState('# Doc\n\n<SQLV2 nodeId="up" code="select 1" returnVariable="events_df" />\n')
        state.runStatusResponses.push(DONE_STATUS)
        const context = createMockContext(state)

        const result = await addCellHandler(context, {
            notebook_id: 'aBcD1234',
            cell_type: 'sql',
            code: 'select * from events_df',
        })

        expect(result.node_id).toBeTruthy()
        expect(result.dataframe_name).toBe('sql_df')

        // First save inserts the cell; the tag carries identity, code, and name.
        const inserted = state.saveBodies[0].content.content[0].attrs.markdown
        expect(inserted).toContain(`nodeId="${result.node_id}"`)
        expect(inserted).toContain('code="select * from events_df"')
        expect(inserted).toContain('returnVariable="sql_df"')
        expect(state.saveBodies[0].version).toBe(3)

        // The run carries the whole sibling namespace as refs; backend filters usage.
        expect(state.runBodies[0]).toMatchObject({
            node_id: result.node_id,
            node_type: 'hogql',
            output_name: 'sql_df',
            refs: { events_df: { node_id: 'up', kind: 'hogql' } },
        })

        // Second save writes runId + result into the tag so the editor renders the output.
        const writtenBack = state.saveBodies[1].content.content[0].attrs.markdown
        expect(writtenBack).toContain('runId="run-1"')
        expect(writtenBack).toContain('"row_count":1')

        // Model-facing result keeps the preview but never the base64 media payload.
        expect(result.run).toMatchObject({ status: 'done', rows_preview: [[1]], stdout: 'hello' })
        expect(result.run!.media).toEqual([{ mime_type: 'image/png' }])
        expect(JSON.stringify(result.run)).not.toContain('aGVsbG8=')

        // Run output is attacker-influenceable (query rows, stdout), so the response must
        // ship inside the untrusted-data boundary the model is told not to obey.
        const formatted = (result as any)[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]
        expect(formatted).toContain('<notebook-cell-run')
        expect(formatted).toContain('not instructions')
    })

    it('add cell returns running with the run_id when the cell outlives the wait budget', async () => {
        vi.useFakeTimers()
        const state = makeState('# Doc\n')
        // Enough queued 'running' responses to outlast the 45s budget at max poll spacing.
        for (let i = 0; i < 60; i++) {
            state.runStatusResponses.push({ status: 'running', result: null, error: null })
        }
        const context = createMockContext(state)

        const pending = addCellHandler(context, {
            notebook_id: 'aBcD1234',
            cell_type: 'python',
            code: 'import time\ntime.sleep(600)',
        })
        await vi.advanceTimersByTimeAsync(60_000)
        const result = await pending

        expect(result.run).toMatchObject({ status: 'running', run_id: 'run-1' })
        // Write-back still pins runId so the run is recoverable; no result prop yet.
        const writtenBack = state.saveBodies[1].content.content[0].attrs.markdown
        expect(writtenBack).toContain('runId="run-1"')
        expect(writtenBack).not.toContain('result={')
    })

    it('add markdown cell appends prose without dispatching a run', async () => {
        const state = makeState('# Doc\n')
        const context = createMockContext(state)

        const result = await addCellHandler(context, {
            notebook_id: 'aBcD1234',
            cell_type: 'markdown',
            markdown: 'Some **notes**.',
        })
        await addCellHandler(context, {
            notebook_id: 'aBcD1234',
            cell_type: 'markdown',
            markdown: 'More notes.',
        })

        expect(result).toEqual({})
        expect(state.runBodies).toHaveLength(0)
        // Each cell is a node of its own: one blank line would fold consecutive prose cells
        // into a single card in the editor, two keeps them separate.
        expect(state.saveBodies[1].content.content[0].attrs.markdown).toBe(
            '# Doc\n\n\nSome **notes**.\n\n\nMore notes.\n'
        )
    })

    it('add component cell inserts the tag with a minted nodeId and no run', async () => {
        const state = makeState('# Doc\n')
        const context = createMockContext(state)

        const result = await addCellHandler(context, {
            notebook_id: 'aBcD1234',
            cell_type: 'component',
            tag_name: 'Query',
            props: { query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } } },
        })

        const inserted = state.saveBodies[0].content.content[0].attrs.markdown
        expect(inserted).toContain(`<Query query={{"kind":"InsightVizNode"`)
        expect(inserted).toContain(`nodeId="${result.node_id}"`)
        expect(state.runBodies).toHaveLength(0)
    })

    // The header title is what a reader skims instead of the code, so every tag-backed cell type
    // has to carry it through to the markdown.
    it.each([
        ['sql', { cell_type: 'sql', code: 'select 1' }, 'SQLV2'],
        ['python', { cell_type: 'python', code: 'x = 1' }, 'PythonV2'],
        ['saved_insight', { cell_type: 'saved_insight', insight_short_id: 'iNs12345' }, 'Query'],
        ['component', { cell_type: 'component', tag_name: 'Image', props: { src: 'https://ph.com/a.png' } }, 'Image'],
    ] satisfies [string, Omit<AddCellParams, 'notebook_id' | 'title'>, string][])(
        'add %s cell writes the title onto the tag',
        async (_label, params, tagName) => {
            const state = makeState('# Doc\n')
            state.runStatusResponses.push(DONE_STATUS)
            const context = createMockContext(state)

            await addCellHandler(context, { ...params, notebook_id: 'aBcD1234', title: 'Weekly signups by source' })

            const inserted = state.saveBodies[0].content.content[0].attrs.markdown
            expect(inserted).toContain(`<${tagName} `)
            expect(inserted).toContain('title="Weekly signups by source"')
        }
    )

    it('markdown cell rejects a title, pointing at a markdown heading instead', async () => {
        const state = makeState('# Doc\n')
        const context = createMockContext(state)

        await expect(
            addCellHandler(context, {
                notebook_id: 'aBcD1234',
                cell_type: 'markdown',
                markdown: 'Some notes.',
                title: 'Notes',
            })
        ).rejects.toThrow(/heading in the markdown/)
        expect(state.saveBodies).toHaveLength(0)
    })

    it('component cell keeps a title carried in its own props', async () => {
        const state = makeState('# Doc\n')
        const context = createMockContext(state)

        await addCellHandler(context, {
            notebook_id: 'aBcD1234',
            cell_type: 'component',
            tag_name: 'Image',
            props: { src: 'https://ph.com/a.png', title: 'From props' },
        })

        expect(state.saveBodies[0].content.content[0].attrs.markdown).toContain('title="From props"')
    })

    it('component cell rejects executable tags', async () => {
        const state = makeState('# Doc\n')
        const context = createMockContext(state)

        await expect(
            addCellHandler(context, {
                notebook_id: 'aBcD1234',
                cell_type: 'component',
                tag_name: 'SQLV2',
                props: { code: 'select 1' },
            })
        ).rejects.toThrow(/cell_type 'sql' or 'python'/)
        expect(state.saveBodies).toHaveLength(0)
    })

    // The legacy SQL cell: a Query node rendering HogQL results without a run, a dataframe name, or
    // run history. Reachable only through the component escape hatch, so it is blocked there too.
    it.each([
        ['a SQL chart', { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'select 1' } }],
        ['a SQL result table', { kind: 'DataTableNode', source: { kind: 'HogQLQuery', query: 'select 1' } }],
    ])('component cell rejects %s, directing SQL to a sql cell', async (_label, query) => {
        const state = makeState('# Doc\n')
        const context = createMockContext(state)

        await expect(
            addCellHandler(context, {
                notebook_id: 'aBcD1234',
                cell_type: 'component',
                tag_name: 'Query',
                props: { query },
            })
        ).rejects.toThrow(/cell_type 'sql'/)
        expect(state.saveBodies).toHaveLength(0)
    })

    it('rejects legacy rich-text notebooks', async () => {
        const state = makeState('unused')
        const context = createMockContext(state)
        ;(context.api.request as any).mockResolvedValueOnce({
            short_id: 'aBcD1234',
            content: { type: 'doc', content: [{ type: 'paragraph' }] },
            version: 1,
        })

        await expect(
            addCellHandler(context, { notebook_id: 'aBcD1234', cell_type: 'sql', code: 'select 1' })
        ).rejects.toThrow(/not a markdown notebook/)
        expect(state.saveBodies).toHaveLength(0)
    })

    it('update cell replaces code, re-runs, and reports stale dependents', async () => {
        const state = makeState(
            [
                '# Doc',
                '',
                '<SQLV2 nodeId="target" code="select 1" returnVariable="df" runId="old" />',
                '',
                '<PythonV2 nodeId="reader" code="df.head()" returnVariable="out" />',
                '',
            ].join('\n')
        )
        state.runStatusResponses.push(DONE_STATUS)
        const context = createMockContext(state)

        const result = await updateCellHandler(context, {
            notebook_id: 'aBcD1234',
            node_id: 'target',
            code: 'select 2',
        })

        expect(state.saveBodies[0].content.content[0].attrs.markdown).toContain('code="select 2"')
        expect(state.runBodies[0]).toMatchObject({ node_id: 'target', code: 'select 2' })
        expect(result.stale_dependents).toEqual([{ node_id: 'reader', dataframe_name: 'out' }])
        // Write-back replaces the stale runId in place.
        const writtenBack = state.saveBodies[1].content.content[0].attrs.markdown
        expect(writtenBack).toContain('runId="run-1"')
        expect(writtenBack).not.toContain('runId="old"')
    })

    it('delete cell removes the tag and lists orphaned dependents', async () => {
        const state = makeState(
            [
                '# Doc',
                '',
                '<SQLV2 nodeId="target" code="select 1" returnVariable="df" />',
                '',
                '<PythonV2 nodeId="reader" code="df.head()" returnVariable="" />',
                '',
            ].join('\n')
        )
        const context = createMockContext(state)

        const result = await deleteCellHandler(context, { notebook_id: 'aBcD1234', node_id: 'target' })

        expect(result).toEqual({ deleted: true, orphaned_dependents: [{ node_id: 'reader' }] })
        expect(state.saveBodies[0].content.content[0].attrs.markdown).not.toContain('SQLV2')
        expect(state.saveBodies[0].content.content[0].attrs.markdown).toContain('reader')
    })

    it('create markdown notebook posts the wrapper document with a title heading', async () => {
        const state = makeState('')
        const context = createMockContext(state)

        const result = await createMarkdownHandler(context, { title: 'Signup analysis', markdown: 'Intro.' })

        expect(result).toMatchObject({ notebook_id: 'nEw12345', title: 'Signup analysis' })
        const body = state.createBodies[0]
        expect(body.title).toBe('Signup analysis')
        expect(body.content).toEqual({
            type: 'doc',
            content: [
                {
                    type: 'ph-markdown-notebook',
                    attrs: { nodeId: 'markdown-notebook-v2', markdown: '# Signup analysis\n\nIntro.' },
                },
            ],
        })
    })
})
