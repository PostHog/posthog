import { useEffect } from 'react'

import { serializeNode } from 'lib/components/MarkdownNotebook/markdown'
import type { NotebookComponentBlockNode } from 'lib/components/MarkdownNotebook/types'
import { getSerializableProps } from 'lib/components/MarkdownNotebook/utils'
import type { NotebookNodeSQLV2Result } from 'scenes/notebooks/Nodes/NotebookNodeSQLV2'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { notebookCodeCellLogic } from '../notebookCodeCellLogic'
import { notebookAppLogic } from './notebookAppLogic'

export function NotebookAppChoiceSource({
    shortId,
    cell,
}: {
    shortId: string
    cell: NotebookComponentBlockNode
}): null {
    const app = notebookAppLogic({ shortId })
    const logic = notebookCodeCellLogic(
        cell.id,
        notebookLogic({ shortId }),
        {
            runId: typeof cell.props.runId === 'string' ? cell.props.runId : null,
            result: cell.props.result as NotebookNodeSQLV2Result | undefined,
        },
        (attributes) => {
            const source = app.values.cells.find((candidate) => candidate.id === cell.id)
            if (source?.type === 'component') {
                app.actions.updateCellOutput(
                    cell.id,
                    serializeNode({
                        ...source,
                        raw: undefined,
                        props: { ...source.props, ...getSerializableProps(attributes) },
                    })
                )
            }
        }
    )
    useEffect(() => logic.mount(), [logic])
    return null
}
