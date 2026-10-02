import { BreakdownTableColumn, ComparedValue, compareByCurrent } from './breakdownTableColumn'

interface Row {
    name: string
    value: ComparedValue | null
}

const rows: Row[] = [
    { name: 'Missing A', value: null },
    { name: 'Positive', value: [10, -50] },
    { name: 'Negative', value: [-5, 100] },
    { name: 'Missing B', value: null },
    { name: 'Zero', value: [0, null] },
]

const column: BreakdownTableColumn<Row> = {
    key: 'value',
    title: 'Value',
    exportLabel: 'Value',
    value: (row) => row.value,
}

describe('compareByCurrent', () => {
    it.each([
        [1, ['Negative', 'Zero', 'Positive', 'Missing A', 'Missing B']],
        [-1, ['Positive', 'Zero', 'Negative', 'Missing A', 'Missing B']],
    ] as const)('keeps missing values last under the LemonTable sort-order contract (%s)', (order, expected) => {
        const sorter = compareByCurrent(column, order)
        const sorted = rows.slice().sort((a, b) => order * sorter(a, b))

        expect(sorted.map((row) => row.name)).toEqual(expected)
    })
})
