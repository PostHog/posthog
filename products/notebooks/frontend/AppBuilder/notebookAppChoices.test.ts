import { MAX_NOTEBOOK_VARIABLE_VALUE_CHARS } from 'scenes/notebooks/Notebook/notebookVariables'

import { hiddenChoiceSources, queryChoices } from './notebookAppChoices'
import { appSourceCells } from './notebookAppLayout'

it('preserves scalar options in result order and skips unusable values', () => {
    const rows = [
        null,
        {},
        [],
        [null, ''],
        [0, false],
        [1, 0],
        [2, '0'],
        [3, {}],
        [4, 'a'.repeat(MAX_NOTEBOOK_VARIABLE_VALUE_CHARS + 1)],
    ]
    expect(queryChoices(['index', ' choice '], rows, ' choice ', false)).toEqual({
        values: ['false', '0'],
        partial: false,
    })
})

it('marks choices as partial only when the result or the distinct choice list is truncated', () => {
    const values = Array.from({ length: 100 }, (_, index) => String(index))
    const rows = [...values.map((value) => [value]), ['0']]
    expect(queryChoices(['choice'], rows, 'choice', false)).toEqual({ values, partial: false })
    expect(queryChoices(['choice'], rows, 'choice', true)).toEqual({ values, partial: true })
    expect(queryChoices(['choice'], [...rows, ['another']], 'choice', false)).toEqual({ values, partial: true })
})

it('keeps a single run observer for each option source without a mounted output', () => {
    const cells = appSourceCells('<SQLV2 nodeId="regions" code="SELECT 1" />')
    const input = {
        id: 'chooser',
        tab_id: 'main',
        kind: 'input' as const,
        input_kind: 'query_select' as const,
        node_id: 'regions',
    }
    const output = { id: 'table', tab_id: 'details', kind: 'cell' as const, node_id: 'regions' }
    expect(hiddenChoiceSources(cells, [input, { ...input, id: 'second' }, output], 'main')).toEqual(cells)
    expect(hiddenChoiceSources(cells, [input, output], 'details')).toEqual([])
    expect(hiddenChoiceSources(cells, [input, { ...output, display: 'source' }], 'details')).toEqual(cells)
})
