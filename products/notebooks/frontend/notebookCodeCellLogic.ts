import type { BuiltLogic } from 'kea'

import { extractDuckSqlTables, extractPythonIdentifiers } from 'scenes/notebooks/Nodes/notebookNodeContent'
import type { NotebookNodeSQLV2Result } from 'scenes/notebooks/Nodes/NotebookNodeSQLV2'
import { notebookNodeSQLV2Logic, NotebookNodeSQLV2LogicProps } from 'scenes/notebooks/Nodes/notebookNodeSQLV2Logic'
import type { notebookLogicType } from 'scenes/notebooks/Notebook/notebookLogic'

import { prepareNotebookInsightDataframes } from './prepareNotebookInsightDataframes'

export function notebookCodeCellLogic(
    nodeId: string,
    notebook: BuiltLogic<notebookLogicType>,
    attributes: { runId?: string | null; result?: NotebookNodeSQLV2Result | null },
    updateAttributes: NotebookNodeSQLV2LogicProps['updateAttributes']
): ReturnType<typeof notebookNodeSQLV2Logic.build> {
    return notebookNodeSQLV2Logic({
        nodeId,
        notebookShortId: notebook.props.shortId,
        updateAttributes,
        runId: attributes.runId ?? null,
        hasResult: Array.isArray(attributes.result?.first_page) && !attributes.result?.previewOnly,
        hasResultMetadata: !!attributes.result,
        prepareInsightDataframes: (code, nodeType) =>
            prepareNotebookInsightDataframes(
                notebook,
                nodeType === 'python' ? extractPythonIdentifiers(code) : extractDuckSqlTables(code)
            ),
        getContent: () => notebook.values.content ?? null,
        getVariables: () => notebook.values.runnableVariables,
    })
}
