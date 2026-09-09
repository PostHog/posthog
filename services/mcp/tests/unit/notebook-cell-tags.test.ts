import { describe, expect, it } from 'vitest'

import {
    buildCellTag,
    collectRunRefs,
    directDependents,
    findCellTag,
    parseCellTags,
    removeCellTag,
    replaceCellTag,
    uniqueDataframeName,
    upsertProp,
} from '@/tools/notebooks/cellTags'
import { applyVariablePatch, buildRunPlan, resolveCursor } from '@/tools/notebooks/runPlan'

const SQL_TAG = '<SQLV2 nodeId="sql-1" code="select 1 as x\\nfrom events" returnVariable="sql_df" />'
const PY_TAG = '<PythonV2 nodeId="py-1" code="df = sql_df.head()" returnVariable="df" />'
const QUERY_TAG = '<Query nodeId="q-1" query={{"kind":"SavedInsightNode","shortId":"abc"}} hideFilters={true} />'

const DOC = `# Title

Some prose.

${SQL_TAG}

${PY_TAG}

${QUERY_TAG}

More prose.`

describe('notebook cell tags', () => {
    it('parses every cell tag with its identity, name, and JSON-unescaped code', () => {
        const cells = parseCellTags(DOC)
        expect(cells.map((cell) => [cell.tagName, cell.nodeId, cell.returnVariable])).toEqual([
            ['SQLV2', 'sql-1', 'sql_df'],
            ['PythonV2', 'py-1', 'df'],
            ['Query', 'q-1', ''],
        ])
        expect(cells[0]!.code).toBe('select 1 as x\nfrom events')
        // Offsets must address the original document so replace/remove surgery is exact.
        expect(DOC.slice(cells[1]!.start, cells[1]!.end)).toBe(PY_TAG)
    })

    it.each([
        ['replaces an existing string prop', SQL_TAG, 'code', 'select 2', /code="select 2"/],
        ['adds a missing string prop', SQL_TAG, 'runId', 'run-9', /runId="run-9" \/>$/],
        [
            'replaces an existing expression prop',
            '<SQLV2 nodeId="a" result={{"row_count":1}} />',
            'result',
            { row_count: 2 },
            /result=\{\{"row_count":2\}\}/,
        ],
    ] as [string, string, string, unknown, RegExp][])('upsertProp %s', (_name, tag, prop, value, expected) => {
        expect(upsertProp(tag, prop, value)).toMatch(expected)
    })

    it('parses arbitrary component tags so delete/anchor works on every dropdown cell', () => {
        const doc = '<FeatureFlag nodeId="ff-1" id={42} />\n\n<Image nodeId="img-1" src="https://x/y.png" />'
        const cells = parseCellTags(doc)
        expect(cells.map((cell) => [cell.tagName, cell.nodeId])).toEqual([
            ['FeatureFlag', 'ff-1'],
            ['Image', 'img-1'],
        ])
        expect(removeCellTag(doc, findCellTag(doc, 'ff-1')!)).toBe('<Image nodeId="img-1" src="https://x/y.png" />')
    })

    it('upsertProp leaves every other prop byte-identical', () => {
        const tag =
            '<SQLV2 nodeId="a" code="select 1" vizQuery={{"kind":"DataVisualizationNode"}} returnVariable="x" />'
        const next = upsertProp(tag, 'code', 'select 2')
        expect(next).toBe(
            '<SQLV2 nodeId="a" code="select 2" vizQuery={{"kind":"DataVisualizationNode"}} returnVariable="x" />'
        )
    })

    it('build → parse round-trips multiline code and identity', () => {
        const tag = buildCellTag('PythonV2', {
            nodeId: 'n1',
            code: 'import pandas as pd\n\nprint("hi")',
            returnVariable: 'out',
        })
        expect(tag).not.toContain('\n')
        const parsed = parseCellTags(tag)
        expect(parsed).toHaveLength(1)
        expect(parsed[0]!.code).toBe('import pandas as pd\n\nprint("hi")')
        expect(parsed[0]!.nodeId).toBe('n1')
    })

    it('replace and remove keep the surrounding document intact', () => {
        const block = findCellTag(DOC, 'py-1')!
        const replaced = replaceCellTag(DOC, block, upsertProp(block.source, 'runId', 'r1'))
        expect(replaced).toContain('runId="r1"')
        expect(replaced).toContain('Some prose.')
        expect(replaced).toContain(QUERY_TAG)

        const removed = removeCellTag(DOC, findCellTag(DOC, 'py-1')!)
        expect(removed).not.toContain('PythonV2')
        expect(removed).not.toContain('\n\n\n')
        expect(removed).toContain(SQL_TAG)
        expect(removed).toContain(QUERY_TAG)
    })

    it('collectRunRefs sends all named siblings, SQL winning name collisions', () => {
        const cells = parseCellTags(
            [
                '<SQLV2 nodeId="s1" code="select 1" returnVariable="shared" />',
                '<PythonV2 nodeId="p1" code="x = 1" returnVariable="shared" />',
                '<PythonV2 nodeId="p2" code="y = 1" returnVariable="py_only" />',
                '<SQLV2 nodeId="s2" code="select 2" returnVariable="" />',
                '<SQLV2 nodeId="self" code="select 3" returnVariable="me" />',
            ].join('\n\n')
        )
        expect(collectRunRefs(cells, 'self')).toEqual({
            shared: { node_id: 's1', kind: 'hogql' },
            py_only: { node_id: 'p2', kind: 'local' },
        })
    })

    it('directDependents matches whole identifiers only and skips self', () => {
        const cells = parseCellTags(
            [
                '<SQLV2 nodeId="up" code="select 1" returnVariable="df" />',
                '<PythonV2 nodeId="uses" code="df.head()" returnVariable="out" />',
                '<PythonV2 nodeId="similar" code="df_2.head()" returnVariable="" />',
            ].join('\n\n')
        )
        expect(directDependents(cells, 'df', 'up')).toEqual([{ node_id: 'uses', dataframe_name: 'out' }])
    })

    it('uniqueDataframeName suffixes past taken cell and variable names case-insensitively', () => {
        const cells = parseCellTags(
            [
                '<SQLV2 nodeId="a" code="c" returnVariable="SQL_DF" />',
                '<SQLV2 nodeId="b" code="c" returnVariable="sql_df_2" />',
            ].join('\n\n')
        )
        expect(uniqueDataframeName('sql_df', cells)).toBe('sql_df_3')
        expect(uniqueDataframeName('fresh', cells)).toBe('fresh')
        expect(uniqueDataframeName('fresh', cells, ['fresh'])).toBe('fresh_2')
    })

    describe('run plan', () => {
        const cell = (nodeId: string, dependsOn: string[] = [], dependents: string[] = [], extra = {}): any => ({
            node_id: nodeId,
            cell_type: 'sql',
            dataframe_name: nodeId,
            code: `select 1 -- ${nodeId}`,
            status: 'done',
            depends_on: dependsOn,
            dependents,
            ...extra,
        })

        /** Markdown holding one SQL cell per node id, in the given document order. */
        const docFor = (nodeIds: string[]): string =>
            parseCellTags(
                nodeIds
                    .map((nodeId) => `<SQLV2 nodeId="${nodeId}" code="select 1" returnVariable="${nodeId}" />`)
                    .join('\n\n')
            )

        // A cell reads a dataframe out of the kernel namespace, not out of the document above it,
        // so running in document order can bind the previous pass's frame and still report done.
        // These pin that the order follows the edges, and that a linear notebook is untouched.
        it.each([
            {
                shape: 'linear notebook keeps document order',
                doc: ['a', 'b', 'c'],
                cells: [cell('a', [], ['b']), cell('b', ['a'], ['c']), cell('c', ['b'])],
                expected: ['a', 'b', 'c'],
            },
            {
                shape: 'forward reference runs its producer first',
                doc: ['reader', 'producer'],
                cells: [cell('reader', ['producer']), cell('producer', [], ['reader'])],
                expected: ['producer', 'reader'],
            },
            {
                shape: 'diamond runs both middles before the join',
                doc: ['top', 'left', 'right', 'join'],
                cells: [
                    cell('top', [], ['left', 'right']),
                    cell('left', ['top'], ['join']),
                    cell('right', ['top'], ['join']),
                    cell('join', ['left', 'right']),
                ],
                expected: ['top', 'left', 'right', 'join'],
            },
            {
                shape: 'disconnected cells stay in document order',
                doc: ['solo_b', 'solo_a'],
                cells: [cell('solo_b'), cell('solo_a')],
                expected: ['solo_b', 'solo_a'],
            },
        ])('$shape', ({ doc, cells, expected }) => {
            const { plan, cycleNodeIds } = buildRunPlan(cells, docFor(doc))
            expect(plan.map((entry) => entry.node_id)).toEqual(expected)
            expect(cycleNodeIds).toEqual([])
        })

        it('runs a dependency cycle in document order rather than dropping or hanging on it', () => {
            const cells = [cell('x', ['y'], ['y']), cell('y', ['x'], ['x']), cell('free', [], [])]
            const { plan, cycleNodeIds } = buildRunPlan(cells, docFor(['x', 'y', 'free']))

            expect(plan.map((entry) => entry.node_id)).toEqual(['free', 'x', 'y'])
            expect(cycleNodeIds).toEqual(['x', 'y'])
        })

        // A non-runnable cell reaching dispatch would 400 and abort the whole pass.
        it.each([
            {
                reason: 'an embedded insight never runs',
                cells: [cell('a'), cell('embed', [], [], { cell_type: 'saved_insight' })],
                doc: ['a', 'embed'],
            },
            {
                reason: 'a cell with no code has nothing to run',
                cells: [cell('a'), cell('blank')],
                doc: ['a', 'blank'],
                markdown: [
                    '<SQLV2 nodeId="a" code="select 1" returnVariable="a" />',
                    '<SQLV2 nodeId="blank" code="" returnVariable="blank" />',
                ].join('\n\n'),
            },
            {
                reason: 'a cell the document no longer holds cannot be dispatched',
                cells: [cell('a'), cell('ghost')],
                doc: ['a'],
            },
        ])('excludes cells where $reason', ({ cells, doc, markdown }) => {
            const { plan } = buildRunPlan(cells, markdown ? parseCellTags(markdown) : docFor(doc))
            expect(plan.map((entry) => entry.node_id)).toEqual(['a'])
        })

        it('carries the markdown code and node type into the plan, not the truncated state copy', () => {
            const markdown = parseCellTags('<PythonV2 nodeId="py" code="df = frame.head()" returnVariable="df" />')
            const { plan } = buildRunPlan(
                [cell('py', [], [], { cell_type: 'python', code: 'select 1 -- truncated' })],
                markdown
            )

            expect(plan).toEqual([
                {
                    node_id: 'py',
                    node_type: 'python',
                    code: 'df = frame.head()',
                    output_name: 'df',
                    dataframe_name: 'df',
                },
            ])
        })

        // Whole-list replacement makes it easy to drop a variable the caller never mentioned.
        // A patch must only ever touch the names it names.
        it('patches only the named variables, keeping every other value, type, and the order', () => {
            const declared = [
                { name: 'client', type: 'string', value: 'acme' },
                { name: 'start_date', type: 'date', value: '2025-01-01' },
                { name: 'threshold', type: 'number', value: 10 },
            ]

            expect(applyVariablePatch(declared, [{ name: 'start_date', value: '2025-06-01' }])).toEqual([
                { name: 'client', type: 'string', value: 'acme' },
                { name: 'start_date', type: 'date', value: '2025-06-01' },
                { name: 'threshold', type: 'number', value: 10 },
            ])

            // An explicit type re-declares; omitting it keeps what the notebook declared.
            expect(applyVariablePatch(declared, [{ name: 'threshold', value: '20', type: 'string' }])[2]).toEqual({
                name: 'threshold',
                type: 'string',
                value: '20',
            })
        })

        // Ignoring an unknown name would run the notebook on the old value and report success —
        // the exact wrong-numbers failure this tool exists to prevent.
        it.each([
            { case: 'suggests a near name', declared: ['start_date'], patched: 'start_dat', expected: 'start_date' },
            { case: 'lists what is declared', declared: ['client'], patched: 'quarter', expected: 'client' },
        ])('rejects a variable the notebook does not declare and $case', ({ declared, patched, expected }) => {
            const variables = declared.map((name) => ({ name, type: 'string', value: null }))
            expect(() => applyVariablePatch(variables, [{ name: patched, value: 'x' }])).toThrow(
                new RegExp(`${patched}[\\s\\S]*${expected}`)
            )
        })

        it('resolves a cursor to the next cell and refuses one that is not in the plan', () => {
            const { plan } = buildRunPlan([cell('a', [], ['b']), cell('b', ['a'])], docFor(['a', 'b']))

            expect(resolveCursor(plan, undefined)).toBe(0)
            expect(resolveCursor(plan, 'a')).toBe(1)
            // Restarting silently would re-run the notebook and bill a sandbox on a bad string.
            expect(() => resolveCursor(plan, 'deleted-cell')).toThrow(/not a runnable cell/)
        })
    })
})
