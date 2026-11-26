import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { insightQuery, promptSearchesQuery, promptSourcesQuery } from './promptReportQueries'

const WINDOW = { promptId: 'prompt-1', from: '2026-01-01', brandNames: ['example'] }

describe('promptReportQueries', () => {
    it('opens a table with a share column as a SQL table that formats the share as a percentage', () => {
        const sources = promptSourcesQuery(WINDOW)

        expect(insightQuery(sources)).toEqual({
            kind: NodeKind.DataVisualizationNode,
            source: sources.source,
            display: ChartDisplayType.ActionsTable,
            tableSettings: {
                columns: [
                    { column: 'share_of_answers', settings: { formatting: { style: 'percent', decimalPlaces: 1 } } },
                ],
            },
        })
    })

    it('opens a table without a share column as it is', () => {
        const searches = promptSearchesQuery(WINDOW)

        expect(insightQuery(searches)).toBe(searches)
    })
})
