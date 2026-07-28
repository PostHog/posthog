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

    it('uniqueDataframeName suffixes past taken names case-insensitively', () => {
        const cells = parseCellTags(
            [
                '<SQLV2 nodeId="a" code="c" returnVariable="SQL_DF" />',
                '<SQLV2 nodeId="b" code="c" returnVariable="sql_df_2" />',
            ].join('\n\n')
        )
        expect(uniqueDataframeName('sql_df', cells)).toBe('sql_df_3')
        expect(uniqueDataframeName('fresh', cells)).toBe('fresh')
    })
})
