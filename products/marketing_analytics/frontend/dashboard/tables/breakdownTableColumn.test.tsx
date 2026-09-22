import { cleanup, render, screen } from '@testing-library/react'

import { LemonTable } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'

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
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each([
        [1, ['Negative', 'Zero', 'Positive', 'Missing A', 'Missing B']],
        [-1, ['Positive', 'Zero', 'Negative', 'Missing A', 'Missing B']],
    ] as const)('keeps missing values last when LemonTable sorts with order %s', (order, expected) => {
        render(
            <LemonTable
                rowKey="name"
                dataSource={rows}
                useURLForSorting={false}
                sorting={{ columnKey: column.key, order }}
                columns={[
                    {
                        key: column.key,
                        title: column.title,
                        sorter: compareByCurrent(column, order),
                        render: (_, row) => row.name,
                    },
                ]}
            />
        )

        expect(screen.getAllByRole('cell').map((cell) => cell.textContent)).toEqual(expected)
    })
})
