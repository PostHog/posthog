import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { collectNotebookFrameNodes } from 'scenes/notebooks/Nodes/notebookNodeContent'
import { collectSqlV2Refs } from 'scenes/notebooks/Nodes/notebookNodeSQLV2Logic'
import { buildMarkdownNotebookContent } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import * as queries from '~/queries/query'
import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { InsightLogicProps } from '~/types'

import { notebookCodeCellLogic } from './notebookCodeCellLogic'
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

    it('prepares on first use and persists only completed result metadata', async () => {
        const content = notebook.values.content
        mountCreator()
        await expectLogic(creator).toFinishAllListeners()
        expect(api.notebooks.sqlV2Run).not.toHaveBeenCalled()
        expect(attributes).toEqual({})
        await creator.asyncActions.syncDataframe()
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

    it('does not run on mount, rename, or insight refresh, and reuses a completed query on first use', async () => {
        attributes = {
            returnVariable: 'insight_df',
            runId: 'cached-run',
            result: { columns: ['count'], row_count: 1 },
            dataframeSource: JSON.stringify(insight.values.query),
            dataframeQuery: response.hogql,
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
        expect(api.notebooks.sqlV2Run).not.toHaveBeenCalled()
        await creator.asyncActions.syncDataframe()
        expect(api.notebooks.sqlV2Run).not.toHaveBeenCalled()
        expect(api.notebooks.sqlV2RunResult).toHaveBeenCalledWith('insight-dataframes', 'cached-run')
        expect(attributes.returnVariable).toBe('renamed_df')
    })

    it('exposes saved and inline insights as SQL references and widget frames', () => {
        const content = buildMarkdownNotebookContent(
            '<Insight nodeId="saved" id="example" returnVariable="daily_df" dataframeQuery="SELECT 1" result={{"columns":["count"],"types":[["count","Int64"]],"row_count":1}} />\n\n' +
                `<Query nodeId="inline" query={${JSON.stringify(insightProps.query)}} returnVariable="inline_df" />`
        )
        expect(collectSqlV2Refs(content, 'consumer')).toMatchObject({
            daily_df: { node_id: 'saved', kind: 'hogql' },
        })
        expect(collectNotebookFrameNodes(content)).toEqual([
            expect.objectContaining({ name: 'daily_df', hasRun: true, columns: [['count', 'Int64']] }),
        ])
    })

    it('retries a failed preparation without creating another cell', async () => {
        jest.mocked(api.notebooks.sqlV2Run).mockRejectedValueOnce(new Error('Temporary query failure'))
        mountCreator()
        await expectLogic(creator).toFinishAllListeners()
        await creator.asyncActions.syncDataframe()
        expect(creator.values.error).toBeTruthy()
        creator.actions.retry()
        await expectLogic(creator).toFinishAllListeners()
        expect(api.notebooks.sqlV2Run).toHaveBeenCalledTimes(2)
        expect(attributes.runId).toBe('insight-run')
    })

    it.each(['', 'invalid-name'])('does not prepare a dataframe named %p', async (returnVariable) => {
        attributes = { returnVariable }
        notebook.actions.setLocalContent(
            buildMarkdownNotebookContent(
                `<Insight nodeId="source" id="example" returnVariable=${JSON.stringify(returnVariable)} />`
            )
        )
        mountCreator()
        await expectLogic(creator).toFinishAllListeners()
        await creator.asyncActions.syncDataframe()
        expect(api.notebooks.sqlV2Run).not.toHaveBeenCalled()
    })

    it.each(['edited', 'removed'])(
        'discards a completed run when its insight was %s during preparation',
        async (change) => {
            const completedResult = await api.notebooks.sqlV2RunResult('insight-dataframes', 'insight-run')
            jest.mocked(api.notebooks.sqlV2RunResult).mockImplementationOnce(async () => {
                notebook.actions.setLocalContent(
                    buildMarkdownNotebookContent(
                        change === 'removed'
                            ? ''
                            : '<Query nodeId="source" query={{"kind":"HogQLQuery","query":"SELECT 2"}} />'
                    )
                )
                return completedResult
            })
            mountCreator()
            await creator.asyncActions.syncDataframe()
            expect(attributes).toEqual({})
            expect(creator.values.error).toBe('The insight changed while preparing its dataframe. Try again.')
            expect(creator.values.isPreparing).toBe(false)
            expect(creator.values.isBusy).toBe(false)
        }
    )

    it('shares a preparation between simultaneous consumers', async () => {
        mountCreator()
        await Promise.all([creator.asyncActions.syncDataframe(), creator.asyncActions.syncDataframe()])
        expect(api.notebooks.sqlV2Run).toHaveBeenCalledTimes(1)
        expect(attributes.runId).toBe('insight-run')
        expect(creator.values.error).toBeNull()
    })

    it('prepares an insight on first reference before dispatching the consuming SQL cell', async () => {
        jest.spyOn(queries, 'performQuery').mockResolvedValue(response)
        const consumer = notebookCodeCellLogic('consumer', notebook, {}, jest.fn())
        const unmount = consumer.mount()
        try {
            await consumer.asyncActions.runQuery('SELECT * FROM insight_df', {})
            await expectLogic(consumer).toFinishAllListeners()
            expect(api.notebooks.sqlV2Run).toHaveBeenNthCalledWith(
                1,
                'insight-dataframes',
                expect.objectContaining({ node_id: 'source', reuse_results: true })
            )
            expect(api.notebooks.sqlV2Run).toHaveBeenNthCalledWith(
                2,
                'insight-dataframes',
                expect.objectContaining({
                    node_id: 'consumer',
                    refs: { insight_df: { node_id: 'source', kind: 'hogql' } },
                })
            )
            expect(collectNotebookFrameNodes(notebook.values.content)).toEqual([
                expect.objectContaining({ name: 'insight_df', hasRun: true }),
            ])
        } finally {
            unmount()
        }
    })

    it.each(['failed', 'interrupted'] as const)('does not cache a %s run and retries it', async (status) => {
        jest.mocked(api.notebooks.sqlV2RunResult).mockResolvedValueOnce({
            status,
            result: null,
            error: 'Query did not finish',
        })
        mountCreator()
        await creator.asyncActions.syncDataframe()
        expect(attributes).toEqual({})
        expect(creator.values.error).toBe('Query did not finish')
        await creator.asyncActions.syncDataframe()
        expect(attributes.runId).toBe('insight-run')
        expect(api.notebooks.sqlV2Run).toHaveBeenCalledTimes(2)
    })
})
