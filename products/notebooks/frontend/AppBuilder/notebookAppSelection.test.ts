import type { NotebookVariable } from 'scenes/notebooks/Notebook/notebookVariables'

import { resolveAppSelection } from './notebookAppSelection'

describe('app selections', () => {
    it('rejects an oversized result before loading its condition', async () => {
        await expect(
            resolveAppSelection(
                { column: 'value', variable: 'target', condition: 'value != null' },
                { value: 'x'.repeat(1_000_000) },
                [{ name: 'target', type: 'string', value: null }]
            )
        ).resolves.toBeNull()
    })
    it.each<[NotebookVariable['type'], string | number | boolean, unknown]>([
        ['boolean', 'false', false],
        ['boolean', 'unknown', null],
        ['number', '0', 0],
        ['number', '', null],
        ['date', '2024-02-29', '2024-02-29'],
        ['date', '2026-02-30', null],
        ['list', '🦔'.repeat(1001), null],
    ])('applies only compatible result values to a %s input', async (type, value, expected) => {
        const input = await resolveAppSelection(
            { variable: 'target', column: 'selected', condition_bytecode: [] },
            { selected: value },
            [{ name: 'target', type, value: null }]
        )
        expect(input).toEqual(expected === null ? null : { name: 'target', value: expected })
    })
})
