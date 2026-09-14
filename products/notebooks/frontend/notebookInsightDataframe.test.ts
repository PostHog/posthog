import { expectLogic } from 'kea-test-utils'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { collectSqlV2Nodes } from 'scenes/notebooks/Nodes/notebookNodeContent'
import { collectSqlV2Refs } from 'scenes/notebooks/Nodes/notebookNodeSQLV2Logic'
import { buildMarkdownNotebookContent } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { performQuery } from '~/queries/query'
import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { InsightLogicProps } from '~/types'

import { notebookInsightDataframeLogic } from './notebookInsightDataframeLogic'

jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))

describe('insight dataframes', () => {
    let logic: ReturnType<typeof notebookLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = notebookLogic({ shortId: 'insight-dataframes', mode: 'canvas' })
        logic.mount()
        logic.actions.setEditable(true)
    })

    afterEach(() => logic.unmount())

    it('creates referenceable SQL cells without colliding with existing SQL or Python names', async () => {
        logic.actions.setLocalContent(
            buildMarkdownNotebookContent(
                '<SQLV2 nodeId="sql" returnVariable="insight_df" code="select 1" />\n\n' +
                    '<PythonV2 nodeId="python" returnVariable="insight_df_2" code="insight_df.copy()" />'
            )
        )

        logic.actions.insertInsightDataframe('select event, count() from events group by event')
        await expectLogic(logic).toFinishAllListeners()

        const cells = collectSqlV2Nodes(logic.values.content)
        expect(cells).toHaveLength(2)
        expect(cells[1]).toMatchObject({
            code: 'select event, count() from events group by event',
            returnVariable: 'insight_df_3',
        })
        expect(collectSqlV2Refs(logic.values.content, 'reader').insight_df_3).toEqual({
            node_id: cells[1].nodeId,
            kind: 'hogql',
        })
    })

    it('loads SQL for a cached insight and ignores a second click while loading', async () => {
        const source: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        }
        const insightProps: InsightLogicProps = {
            dashboardItemId: 'new-AdHoc.dataframe-test',
            query: { kind: NodeKind.InsightVizNode, source },
        }
        const data = dataNodeLogic({
            key: insightVizDataNodeKey(insightProps),
            query: source,
            cachedResults: { results: [] },
        })
        const insight = insightDataLogic(insightProps)
        const creator = notebookInsightDataframeLogic({ notebookLogic: logic, insightProps })
        data.mount()
        insight.mount()
        creator.mount()
        try {
            jest.mocked(performQuery).mockResolvedValue({ results: [], hogql: 'SELECT count() FROM events' })
            logic.actions.setLocalContent(buildMarkdownNotebookContent(''))
            expect(insight.values.hogQL).toBeNull()

            creator.actions.createDataframe()
            creator.actions.createDataframe()
            await expectLogic(creator).toFinishAllListeners()

            expect(performQuery).toHaveBeenCalledTimes(1)
            expect(collectSqlV2Nodes(logic.values.content)).toEqual([
                expect.objectContaining({ code: 'SELECT count() FROM events', returnVariable: 'insight_df' }),
            ])
            expect(creator.values.isCreatingDataframe).toBe(false)
        } finally {
            creator.unmount()
            insight.unmount()
            data.unmount()
        }
    })
})
