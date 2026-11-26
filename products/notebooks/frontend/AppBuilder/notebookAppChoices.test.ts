import { MAX_NOTEBOOK_VARIABLE_VALUE_CHARS } from 'scenes/notebooks/Notebook/notebookVariables'

import { queryChoices } from './notebookAppChoices'

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
    expect(queryChoices(['index', 'choice'], rows, 'choice', false)).toEqual({ values: ['false', '0'], partial: false })
})

it('marks choices as partial only when the result or the distinct choice list is truncated', () => {
    const values = Array.from({ length: 100 }, (_, index) => String(index))
    const rows = [...values.map((value) => [value]), ['0']]
    expect(queryChoices(['choice'], rows, 'choice', false)).toEqual({ values, partial: false })
    expect(queryChoices(['choice'], rows, 'choice', true)).toEqual({ values, partial: true })
    expect(queryChoices(['choice'], [...rows, ['another']], 'choice', false)).toEqual({ values, partial: true })
})
