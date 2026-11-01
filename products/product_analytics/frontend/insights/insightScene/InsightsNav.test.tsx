import { cleanup, fireEvent, render } from '@testing-library/react'
import { BindLogic } from 'kea'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { DataTableNode, InsightVizNode, NodeKind, WebStatsBreakdown } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId } from '~/types'

import { InsightsNav } from './InsightsNav'

const insightLogicProps: InsightLogicProps = { dashboardItemId: 'new' as InsightShortId }

const webAnalyticsQuery: InsightVizNode = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.WebStatsTableQuery,
        breakdownBy: WebStatsBreakdown.Page,
        properties: [],
        dateRange: { date_from: '-7d' },
    },
}

const dataTableQuery: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.EventsQuery, select: ['event'] },
}

describe('InsightsNav', () => {
    beforeEach(() => {
        initKeaTests()
        insightLogic(insightLogicProps).mount()
        insightDataLogic(insightLogicProps).mount()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        ['insight-web-analytics-tab', webAnalyticsQuery],
        ['insight-json-tab', dataTableQuery],
    ])('keeps the query when the active %s tab is clicked again', (dataAttr, query) => {
        insightDataLogic(insightLogicProps).actions.setQuery(query)
        const { container } = render(
            <BindLogic logic={insightLogic} props={insightLogicProps}>
                <InsightsNav />
            </BindLogic>
        )

        fireEvent.click(container.querySelector(`[data-attr="${dataAttr}"]`)!)

        expect(insightDataLogic(insightLogicProps).values.query).toEqual(query)
    })
})
