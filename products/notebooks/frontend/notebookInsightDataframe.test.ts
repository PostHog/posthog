import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { collectNotebookFrameNodes } from 'scenes/notebooks/Nodes/notebookNodeContent'
import { collectSqlV2Refs, notebookNodeSQLV2Logic } from 'scenes/notebooks/Nodes/notebookNodeSQLV2Logic'
import { buildMarkdownNotebookContent } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { InsightLogicProps } from '~/types'

import { InsightDataframeAttributes, notebookInsightDataframeLogic } from './notebookInsightDataframeLogic'

describe('insight dataframes', () => {
    let notebook: ReturnType<typeof notebookLogic.build>
    let data: ReturnType<typeof dataNodeLogic.build>
    let insight: ReturnType<typeof insightDataLogic.build>
    let creator: ReturnType<typeof notebookInsightDataframeLogic.build>
    let attributes: InsightDataframeAttributes
    let insightProps: InsightLogicProps
    const response = { results: [], hogql: 'SELECT count() FROM events', last_refresh: '2026-01-01T00:00:00Z' }

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.notebooks, 'sqlV2Run').mockResolvedValue({ run_id: 'insight-run', starts_sandbox: false })
        jest.spyOn(api.notebooks, 'sqlV2RunResult').mockResolvedValue({
            status: 'done',
            result: { columns: ['count'], types: [['count', 'Int64']], row_count: 1, first_page: [[12]] },
            rows: [[12]],
            error: null,
        })
        notebook = notebookLogic({ shortId: 'insight-dataframes', mode: 'canvas' })
        notebook.mount()
        notebook.actions.setEditable(true)
        const source: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        }
        insightProps = { dashboardItemId: 'new-AdHoc.dataframe-test', query: { kind: NodeKind.InsightVizNode, source } }
        notebook.actions.setLocalContent(
            buildMarkdownNotebookContent(`<Query nodeId="source" query={${JSON.stringify(insightProps.query)}} />`)
        )
        data = dataNodeLogic({ key: insightVizDataNodeKey(insightProps), query: source, cachedResults: response })
        insight = insightDataLogic(insightProps)
        data.mount()
        insight.mount()
        attributes = {}
    })

    afterEach(() => {
        creator?.unmount()
        insight.unmount()
        data.unmount()
        notebook.unmount()
        jest.restoreAllMocks()
    })

    function mountCreator(): void {
        creator = notebookInsightDataframeLogic({
            notebookLogic: notebook,
            nodeId: 'source',
            insightProps,
            attributes,
            enabled: true,
            updateAttributes: (patch) => {
                attributes = { ...attributes, ...patch }
                notebookInsightDataframeLogic({ ...creator.props, attributes })
            },
        })
        creator.mount()
    }

    it('prepares the insight itself and persists only result metadata', async () => {
        const content = notebook.values.content
        mountCreator()
        await expectLogic(creator).toFinishAllListeners()
        await expectLogic(notebookNodeSQLV2Logic.findMounted({ nodeId: 'source' })!).toFinishAllListeners()
        expect(api.notebooks.sqlV2Run).toHaveBeenCalledTimes(1)
        expect(api.notebooks.sqlV2Run).toHaveBeenCalledWith(
            'insight-dataframes',
            expect.objectContaining({
                node_id: 'source',
                code: response.hogql,
            })
        )
        expect(attributes).toMatchObject({
            returnVariable: 'insight_df',
            runId: 'insight-run',
            dataframeQuery: response.hogql,
        })
        expect(attributes.result).toEqual({
            columns: ['count'],
            types: [['count', 'Int64']],
            row_count: 1,
            has_more: false,
        })
        expect(notebook.values.content).toEqual(content)
    })

    it('reuses a saved run on mount and rename, but replaces it when the insight refreshes', async () => {
        attributes = {
            returnVariable: 'insight_df',
            runId: 'cached-run',
            result: { columns: ['count'], row_count: 1 },
            dataframeSource: JSON.stringify([insight.values.query, response.last_refresh]),
        }
        mountCreator()
        await expectLogic(creator).toFinishAllListeners()
        creator.actions.setReturnVariable('renamed_df')
        await expectLogic(creator).toFinishAllListeners()
        expect(attributes.returnVariable).toBe('renamed_df')
        expect(api.notebooks.sqlV2Run).not.toHaveBeenCalled()
        expect(api.notebooks.sqlV2RunResult).not.toHaveBeenCalled()

        data.actions.loadDataSuccess({ ...response, last_refresh: '2026-01-02T00:00:00Z' })
        await expectLogic(creator).toFinishAllListeners()
        expect(api.notebooks.sqlV2Run).toHaveBeenCalledTimes(1)
        expect(attributes.returnVariable).toBe('renamed_df')
    })

    it('exposes saved and inline insights as SQL references and widget frames', () => {
        const content = buildMarkdownNotebookContent(
            '<Insight nodeId="saved" id="example" returnVariable="daily_df" dataframeQuery="SELECT 1" result={{"columns":["count"],"types":[["count","Int64"]],"row_count":1}} />\n\n' +
                `<Query nodeId="inline" query={${JSON.stringify(insightProps.query)}} returnVariable="inline_df" />`
        )
        expect(collectSqlV2Refs(content, 'consumer')).toMatchObject({
            daily_df: { node_id: 'saved', kind: 'hogql' },
            inline_df: { node_id: 'inline', kind: 'hogql' },
        })
        expect(collectNotebookFrameNodes(content)).toEqual([
            expect.objectContaining({ name: 'daily_df', hasRun: true, columns: [['count', 'Int64']] }),
            expect.objectContaining({ name: 'inline_df', hasRun: false }),
        ])
    })

    it('retries a failed preparation without creating another cell', async () => {
        jest.mocked(api.notebooks.sqlV2Run).mockRejectedValueOnce(new Error('Temporary query failure'))
        mountCreator()
        await expectLogic(creator).toFinishAllListeners()
        expect(creator.values.error).toBeTruthy()
        creator.actions.retry()
        await expectLogic(creator).toFinishAllListeners()
        expect(api.notebooks.sqlV2Run).toHaveBeenCalledTimes(2)
        expect(attributes.runId).toBe('insight-run')
    })

    it.each(['', 'invalid-name'])('does not prepare a dataframe named %p', async (returnVariable) => {
        attributes = { returnVariable }
        mountCreator()
        await expectLogic(creator).toFinishAllListeners()
        expect(api.notebooks.sqlV2Run).not.toHaveBeenCalled()
    })
})
