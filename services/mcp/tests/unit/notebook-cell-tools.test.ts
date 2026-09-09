import { afterEach, describe, expect, it, vi } from 'vitest'

import { addCellHandler } from '@/tools/notebooks/addCell'
import { createMarkdownHandler } from '@/tools/notebooks/createMarkdown'
import { deleteCellHandler } from '@/tools/notebooks/deleteCell'
import { runAllCellsHandler } from '@/tools/notebooks/runAllCells'
import { setVariablesHandler } from '@/tools/notebooks/setVariables'
import { updateCellHandler } from '@/tools/notebooks/updateCell'
import { formatNotebookWidgetCatalogForAgents } from '@/tools/notebooks/widgetCatalog'
import { getToolDefinition } from '@/tools/toolDefinitions'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, type Context } from '@/tools/types'

import notebookWidgetCatalog from 'products/notebooks/notebook-widget-catalog.json'

type AddCellParams = Parameters<typeof addCellHandler>[1]

interface MockState {
    markdown: string
    version: number
    variables: any[]
    // Another client's variable edit, applied when the next save commits.
    variablesOnSave?: any[]
    saveBodies: any[]
    runBodies: any[]
    runStatusResponses: any[]
    createBodies: any[]
    patchBodies: any[]
    // The sql_v2/state view: dependency edges and per-cell run state.
    cells: any[]
    // Merged into every dispatch response, for the sandbox-cost signal.
    dispatchExtra?: Record<string, unknown>
    // Thrown by the next dispatch instead of answering it.
    dispatchError?: unknown
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
        if (opts.method === 'GET' && path.endsWith('/sql_v2/state/')) {
            return {
                notebook_id: 'aBcD1234',
                title: 'Doc',
                version: state.version,
                markdown: state.markdown,
                kernel: { status: 'stopped' },
                variables: state.variables,
                cells: state.cells,
            }
        }
        if (opts.method === 'GET') {
            return {
                short_id: 'aBcD1234',
                content: markdownContent(state.markdown),
                version: state.version,
                variables: state.variables,
            }
        }
        if (opts.method === 'PATCH') {
            state.patchBodies.push(opts.body)
            state.variables = opts.body.variables
            return {
                short_id: 'aBcD1234',
                content: markdownContent(state.markdown),
                version: state.version,
                variables: state.variables,
            }
        }
        if (opts.method === 'POST' && path.endsWith('/sql_v2/run/')) {
            if (state.dispatchError) {
                const error = state.dispatchError
                state.dispatchError = undefined
                throw error
            }
            state.runBodies.push(opts.body)
            return { run_id: `run-${state.runBodies.length}`, starts_sandbox: false, ...state.dispatchExtra }
        }
        if (opts.method === 'POST' && path.endsWith('/collab/markdown_save/')) {
            state.saveBodies.push(opts.body)
            state.markdown = opts.body.content.content[0].attrs.markdown
            state.version += 1
            if (state.variablesOnSave) {
                state.variables = state.variablesOnSave
                state.variablesOnSave = undefined
            }
            // The real endpoint answers an accepted save with the full notebook, variables included.
            return {
                short_id: 'aBcD1234',
                content: opts.body.content,
                version: state.version,
                variables: state.variables,
            }
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

function makeState(markdown: string, variables: any[] = [], cells: any[] = []): MockState {
    return {
        markdown,
        version: 3,
        variables,
        saveBodies: [],
        runBodies: [],
        runStatusResponses: [],
        createBodies: [],
        patchBodies: [],
        cells,
    }
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

    it('keeps every object widget view in the shared vocabulary', () => {
        const standardViewNames = new Set(Object.keys(notebookWidgetCatalog.viewConventions))

        for (const widget of Object.values(notebookWidgetCatalog.widgets)) {
            expect(standardViewNames.has(widget.defaultView.name)).toBe(true)
            expect(Object.keys(widget.views).every((viewName) => standardViewNames.has(viewName))).toBe(true)
        }
    })

    it('describes compound widget identity to notebook-building agents', () => {
        const catalogPrompt = formatNotebookWidgetCatalogForAgents()

        expect(catalogPrompt).toContain('<Group id="group-key" groupTypeIndex={0} view="summary" />')
        expect(catalogPrompt).toContain('"attrs":{"id":"group-key","groupTypeIndex":0,"view":"summary"}')
        expect(catalogPrompt).toContain('groupTypeIndex: Numeric group type index.')
    })

    it('add sql cell inserts the tag, runs with sibling refs and variables, and writes the result back', async () => {
        const country = { name: 'country', type: 'string', value: 'US' }
        const state = makeState('# Doc\n\n<SQLV2 nodeId="up" code="select 1" returnVariable="events_df" />\n', [
            country,
        ])
        state.runStatusResponses.push(DONE_STATUS)
        const context = createMockContext(state)

        const result = await addCellHandler(context, {
            notebook_id: 'aBcD1234',
            cell_type: 'sql',
            code: 'select * from events_df where country = {country}',
        })

        expect(result.node_id).toBeTruthy()
        expect(result.dataframe_name).toBe('sql_df')

        // First save inserts the cell; the tag carries identity, code, and name.
        const inserted = state.saveBodies[0].content.content[0].attrs.markdown
        expect(inserted).toContain(`nodeId="${result.node_id}"`)
        expect(inserted).toContain('code="select * from events_df where country = {country}"')
        expect(inserted).toContain('returnVariable="sql_df"')
        expect(state.saveBodies[0].version).toBe(3)

        // The run carries the whole sibling namespace as refs and the notebook's saved
        // variables; the backend filters usage and fails a `{name}` it was not handed.
        expect(state.runBodies[0]).toMatchObject({
            node_id: result.node_id,
            node_type: 'hogql',
            output_name: 'sql_df',
            refs: { events_df: { node_id: 'up', kind: 'hogql' } },
            variables: [country],
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

    it.each([
        {
            tag: 'Query',
            props: { query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } } },
            expected: '<Query query={{"kind":"InsightVizNode"',
        },
        {
            tag: 'Widget',
            props: { prompt: 'Show weekly signups as an interactive chart' },
            expected: '<Widget prompt="Show weekly signups as an interactive chart"',
        },
    ])('add $tag component cell inserts the tag with a minted nodeId and no run', async ({ tag, props, expected }) => {
        const state = makeState('# Doc\n')
        const context = createMockContext(state)

        const result = await addCellHandler(context, {
            notebook_id: 'aBcD1234',
            cell_type: 'component',
            tag_name: tag,
            props,
        })

        const inserted = state.saveBodies[0].content.content[0].attrs.markdown
        expect(inserted).toContain(expected)
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

    it('saved insight cells use the default panel visibility', async () => {
        const state = makeState('# Doc\n')
        const context = createMockContext(state)

        await addCellHandler(context, {
            notebook_id: 'aBcD1234',
            cell_type: 'saved_insight',
            insight_short_id: 'iNs12345',
        })

        const inserted = state.saveBodies[0].content.content[0].attrs.markdown
        expect(inserted).toContain('query={{"kind":"SavedInsightNode","shortId":"iNs12345"}}')
        expect(inserted).not.toContain('hideFilters')
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

    it('component cell rejects an unsupported object widget view', async () => {
        const state = makeState('# Doc\n')
        const context = createMockContext(state)

        await expect(
            addCellHandler(context, {
                notebook_id: 'aBcD1234',
                cell_type: 'component',
                tag_name: 'FeatureFlag',
                props: { id: 123, view: 'compact-editor' },
            })
        ).rejects.toThrow(/detail, summary, editor, conditions, implementation/)
        expect(state.saveBodies).toHaveLength(0)
    })

    it.each(['notebooks-create', 'notebooks-create-markdown', 'notebooks-add-cell'])(
        '%s advertises object widget views from the shared catalog',
        (toolName) => {
            const description = getToolDefinition(toolName).description

            expect(description).toContain('FeatureFlag')
            expect(description).toContain('summary: Show the flag status')
            expect(description).toContain('editor: Edit the flag status')
            expect(description).toContain('Cohort')
            expect(description).toContain('Filters are hidden by default')
            expect(description).toContain('Add showFilters only when the reader should configure the widget')
        }
    )

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
        expect(state.runBodies[0]).not.toHaveProperty('variables')
        expect(result.stale_dependents).toEqual([{ node_id: 'reader', dataframe_name: 'out' }])
        // Write-back replaces the stale runId in place.
        const writtenBack = state.saveBodies[1].content.content[0].attrs.markdown
        expect(writtenBack).toContain('runId="run-1"')
        expect(writtenBack).not.toContain('runId="old"')
    })

    it.each([
        {
            label: 'add cell',
            markdown: '# Doc\n',
            run: (context: Context) =>
                addCellHandler(context, { notebook_id: 'aBcD1234', cell_type: 'sql', code: 'select {country}' }),
        },
        {
            label: 'update cell',
            markdown: '# Doc\n\n<SQLV2 nodeId="target" code="select 1" returnVariable="df" />\n',
            run: (context: Context) =>
                updateCellHandler(context, { notebook_id: 'aBcD1234', node_id: 'target', code: 'select {country}' }),
        },
    ] as { label: string; markdown: string; run: (context: Context) => Promise<unknown> }[])(
        '$label binds the variables the save returned, not the ones read before it',
        async ({ markdown, run }) => {
            const before = { name: 'country', type: 'string', value: 'US' }
            const after = { name: 'country', type: 'string', value: 'DE' }
            const state = makeState(markdown, [before])
            state.variablesOnSave = [after]
            state.runStatusResponses.push(DONE_STATUS)
            const context = createMockContext(state)

            await run(context)

            expect(state.runBodies[0].variables).toEqual([after])
        }
    )

    it('set variables replaces the list and reports the cells that read a changed one', async () => {
        const state = makeState(
            [
                '# Doc',
                '',
                '<SQLV2 nodeId="by_country" code="select {country}, {limit}" returnVariable="df" />',
                '',
                '<PythonV2 nodeId="reader" code="df.head(limit)" returnVariable="out" />',
                '',
                '<SQLV2 nodeId="unrelated" code="select 1" returnVariable="one" />',
                '',
            ].join('\n'),
            [
                { name: 'country', type: 'string', value: 'US' },
                { name: 'limit', type: 'number', value: 10 },
            ]
        )
        const context = createMockContext(state)

        const result = await setVariablesHandler(context, {
            notebook_id: 'aBcD1234',
            variables: [
                { name: 'country', type: 'string', value: 'US' },
                { name: 'limit', type: 'number', value: 25 },
            ],
        })

        expect(state.patchBodies).toEqual([
            {
                variables: [
                    { name: 'country', type: 'string', value: 'US' },
                    { name: 'limit', type: 'number', value: 25 },
                ],
            },
        ])
        expect(result.variables).toEqual(state.variables)
        // Only `limit` changed: the SQL cell reads it as `{limit}`, the Python cell as a global.
        expect(result.stale_cells).toEqual([
            { node_id: 'by_country', dataframe_name: 'df' },
            { node_id: 'reader', dataframe_name: 'out' },
        ])
        expect((result as any)[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain('<notebook-cell-refs')
    })

    it.each([
        {
            label: 'a duplicate name',
            variables: [
                { name: 'x', type: 'string' as const },
                { name: 'x', type: 'number' as const },
            ],
            message: /unique/,
        },
        {
            label: "a cell's dataframe name",
            variables: [{ name: 'df', type: 'string' as const, value: 'a' }],
            message: /dataframe_name/,
        },
    ])('set variables rejects $label without saving', async ({ variables, message }) => {
        const state = makeState('<SQLV2 nodeId="s" code="select 1" returnVariable="df" />\n')
        const context = createMockContext(state)

        await expect(setVariablesHandler(context, { notebook_id: 'aBcD1234', variables })).rejects.toThrow(message)
        expect(state.patchBodies).toEqual([])
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

    describe('run all cells', () => {
        const THREE_CELL_DOC = [
            '# Weekly research',
            '',
            '<SQLV2 nodeId="one" code="select {client} as c" returnVariable="base" />',
            '',
            '<PythonV2 nodeId="two" code="mid = base.head()" returnVariable="mid" />',
            '',
            '<SQLV2 nodeId="three" code="select * from mid" returnVariable="final" />',
            '',
        ].join('\n')

        const THREE_CELL_STATE = [
            {
                node_id: 'one',
                cell_type: 'sql',
                dataframe_name: 'base',
                code: '',
                status: 'done',
                depends_on: [],
                dependents: ['two'],
            },
            {
                node_id: 'two',
                cell_type: 'python',
                dataframe_name: 'mid',
                code: '',
                status: 'done',
                depends_on: ['one'],
                dependents: ['three'],
            },
            {
                node_id: 'three',
                cell_type: 'sql',
                dataframe_name: 'final',
                code: '',
                status: 'done',
                depends_on: ['two'],
                dependents: [],
            },
        ]

        const threeCellState = (variables: any[] = []): MockState =>
            makeState(THREE_CELL_DOC, variables, structuredClone(THREE_CELL_STATE))

        it('runs every cell in dependency order and writes each result back', async () => {
            const state = threeCellState()
            state.runStatusResponses.push(DONE_STATUS, DONE_STATUS, DONE_STATUS)
            const context = createMockContext(state)

            const result = await runAllCellsHandler(context, { notebook_id: 'aBcD1234' })

            expect(state.runBodies.map((body) => body.node_id)).toEqual(['one', 'two', 'three'])
            expect(result.status).toBe('done')
            expect(result.cells).toEqual([
                { node_id: 'one', dataframe_name: 'base', status: 'done', run_id: 'run-1', row_count: 1 },
                { node_id: 'two', dataframe_name: 'mid', status: 'done', run_id: 'run-2', row_count: 1 },
                { node_id: 'three', dataframe_name: 'final', status: 'done', run_id: 'run-3', row_count: 1 },
            ])
            // Full detail for the answer cell only; the rest are reachable by run_id.
            expect(result.last_run).toMatchObject({ run_id: 'run-3', status: 'done' })
            expect(result.resume).toBeUndefined()

            const finalMarkdown = state.saveBodies.at(-1)!.content.content[0].attrs.markdown
            for (const runId of ['run-1', 'run-2', 'run-3']) {
                expect(finalMarkdown).toContain(`runId="${runId}"`)
            }

            // Rows and stdout are attacker-influenceable, so the whole response is wrapped.
            expect((result as any)[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain('<notebook-cell-run')
        })

        it('patches only the named variables and binds the merged set to every run', async () => {
            const state = threeCellState([
                { name: 'client', type: 'string', value: 'acme' },
                { name: 'start_date', type: 'date', value: '2025-01-01' },
            ])
            state.runStatusResponses.push(DONE_STATUS, DONE_STATUS, DONE_STATUS)
            const context = createMockContext(state)

            const result = await runAllCellsHandler(context, {
                notebook_id: 'aBcD1234',
                variables: [{ name: 'client', value: 'globex' }],
            })

            // One PATCH, carrying the merged list — start_date must survive untouched.
            expect(state.patchBodies).toEqual([
                {
                    variables: [
                        { name: 'client', type: 'string', value: 'globex' },
                        { name: 'start_date', type: 'date', value: '2025-01-01' },
                    ],
                },
            ])
            for (const body of state.runBodies) {
                expect(body.variables).toEqual([
                    { name: 'client', type: 'string', value: 'globex' },
                    { name: 'start_date', type: 'date', value: '2025-01-01' },
                ])
            }
            expect(result.variables).toHaveLength(2)
        })

        it('returns a resumable cursor when the pass outlives its budget', async () => {
            vi.useFakeTimers()
            const state = threeCellState()
            state.runStatusResponses.push(DONE_STATUS)
            // Cell two never finishes, so the pass spends the rest of its budget on it.
            for (let i = 0; i < 60; i++) {
                state.runStatusResponses.push({ status: 'running', result: null, error: null })
            }
            const context = createMockContext(state)

            const pending = runAllCellsHandler(context, { notebook_id: 'aBcD1234' })
            await vi.advanceTimersByTimeAsync(120_000)
            const result = await pending

            expect(result.status).toBe('running')
            // The cursor names the last cell that finished, so cell two is retried or adopted.
            expect(result.resume).toEqual({ resume_after_node_id: 'one', remaining_cells: 2 })
            expect(state.runBodies.map((body) => body.node_id)).toEqual(['one', 'two'])
            expect(result.cells.map((cell) => cell.status)).toEqual(['done', 'running', 'not_run'])
        })

        it('adopts a run already in flight on resume instead of dispatching a duplicate', async () => {
            const state = threeCellState()
            // Cell two is what the previous call left running.
            state.cells[1].status = 'running'
            state.cells[1].last_run = { run_id: 'run-inflight', status: 'running', finished_at: 'now' }
            state.runStatusResponses.push(DONE_STATUS, DONE_STATUS)
            const context = createMockContext(state)

            const result = await runAllCellsHandler(context, {
                notebook_id: 'aBcD1234',
                resume_after_node_id: 'one',
            })

            // Dispatching cell two would 409 against the slot its own run holds.
            expect(state.runBodies.map((body) => body.node_id)).toEqual(['three'])
            expect(result.status).toBe('done')
            expect(result.cells.map((cell) => cell.run_id)).toEqual([undefined, 'run-inflight', 'run-1'])
        })

        it('stops at a failed cell and names what downstream never ran', async () => {
            const state = threeCellState()
            state.runStatusResponses.push(DONE_STATUS, {
                status: 'failed',
                result: null,
                error: "NameError: name 'base' is not defined",
            })
            const context = createMockContext(state)

            const result = await runAllCellsHandler(context, { notebook_id: 'aBcD1234' })

            // Cell three reads the failed cell's dataframe; running it would look fresh but
            // bind the previous pass's frame.
            expect(state.runBodies.map((body) => body.node_id)).toEqual(['one', 'two'])
            expect(result.status).toBe('failed')
            expect(result.failure).toMatchObject({
                node_id: 'two',
                dependent_node_ids: ['three'],
                run: { status: 'failed', error: "NameError: name 'base' is not defined" },
            })
            expect(result.resume).toEqual({ resume_after_node_id: 'one', remaining_cells: 2 })
            expect(result.cells.map((cell) => cell.status)).toEqual(['done', 'failed', 'not_run'])
        })

        it.each([
            {
                case: 'a busy notebook is resumable, not a failure',
                error: Object.assign(new Error('conflict'), { status: 409 }),
            },
            {
                case: 'a team at run capacity is resumable, not a failure',
                error: Object.assign(new Error('too many'), { status: 429 }),
            },
        ])('reports that $case', async ({ error }) => {
            const state = threeCellState()
            state.dispatchError = error
            const context = createMockContext(state)

            const result = await runAllCellsHandler(context, { notebook_id: 'aBcD1234' })

            expect(result.status).toBe('running')
            expect(result.resume).toEqual({ resume_after_node_id: null, remaining_cells: 3 })
        })

        it('surfaces the sandbox price the dispatch reports so the agent can quote it', async () => {
            const state = threeCellState()
            state.dispatchExtra = { starts_sandbox: true, sandbox_hourly_price: 0.42 }
            state.runStatusResponses.push(DONE_STATUS, DONE_STATUS, DONE_STATUS)
            const context = createMockContext(state)

            const result = await runAllCellsHandler(context, { notebook_id: 'aBcD1234' })

            expect(result.sandbox).toEqual({ started: true, hourly_price: 0.42 })
            expect(result.hint).toContain('0.42')
        })

        it('refuses new variable values mid-pass, which would mix two sets in one notebook', async () => {
            const state = threeCellState([{ name: 'client', type: 'string', value: 'acme' }])
            const context = createMockContext(state)

            await expect(
                runAllCellsHandler(context, {
                    notebook_id: 'aBcD1234',
                    resume_after_node_id: 'one',
                    variables: [{ name: 'client', value: 'globex' }],
                })
            ).rejects.toThrow(/only when starting a pass/)
            expect(state.patchBodies).toHaveLength(0)
            expect(state.runBodies).toHaveLength(0)
        })
    })
})
