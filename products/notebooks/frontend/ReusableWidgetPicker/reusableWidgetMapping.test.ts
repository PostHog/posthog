import type { NotebookFrameNodeSummary } from 'scenes/notebooks/Nodes/notebookNodeContent'

import {
    columnMappingHog,
    defaultColumnMapping,
    widgetInputMatches,
    widgetMappingIssues,
} from './reusableWidgetMapping'

const columns = [
    { name: 'category', type: 'String' },
    { name: 'revenue', type: 'Float64' },
]
const frame: NotebookFrameNodeSummary = {
    name: 'sales_df',
    nodeId: 'sales',
    nodeType: 'python',
    hasRun: true,
    columns: [
        ['category', 'String'],
        ['revenue', 'Float64'],
    ],
    rowCount: 2,
    code: '',
}

describe('reusableWidgetMapping', () => {
    it.each([
        [frame.columns, true, []],
        [
            [
                ['category', 'String'],
                ['amount', 'Float64'],
            ],
            false,
            ['Missing column: revenue'],
        ],
        [
            [
                ['category', 'String'],
                ['revenue', 'String'],
            ],
            false,
            ['revenue: expected Float64, found String'],
        ],
        [
            [
                ['revenue', 'Float64'],
                ['category', 'String'],
            ],
            false,
            ['The columns need to be reordered or extra columns removed.'],
        ],
    ] as const)('checks the saved column contract before connecting %j', (sourceColumns, matches, issues) => {
        const source = { ...frame, columns: sourceColumns.map(([name, type]) => [name, type] as [string, string]) }
        expect(widgetInputMatches(columns, source)).toBe(matches)
        expect(widgetMappingIssues(columns, source)).toEqual(issues)
    })

    it('leaves missing columns for the user instead of guessing by position', () => {
        expect(
            defaultColumnMapping(columns, {
                ...frame,
                columns: [
                    ['category', 'String'],
                    ['amount', 'Float64'],
                ],
            })
        ).toEqual({ category: 'category', revenue: '' })
    })

    it('quotes both source and destination column names in generated Hog', () => {
        const hog = columnMappingHog([{ name: "a'b", type: 'String' }], { "a'b": "c\\d'\ne" })
        expect(hog).toContain("{'a\\'b': row['c\\\\d\\'\\ne']}")
        expect(columnMappingHog([], {})).toBe('return rows')
    })
})
