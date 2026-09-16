import type { BuiltLogic } from 'kea'

import { parseMarkdownNotebook, serializeMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import { getSerializableProps } from 'lib/components/MarkdownNotebook/utils'
import {
    collectNotebookDataframeNodes,
    isReferenceableSqlV2FrameName,
} from 'scenes/notebooks/Nodes/notebookNodeContent'
import {
    buildMarkdownNotebookContent,
    getMarkdownNotebookMarkdown,
    getMarkdownNotebookNodeId,
} from 'scenes/notebooks/Notebook/markdownNotebookV2'
import type { notebookLogicType } from 'scenes/notebooks/Notebook/notebookLogic'
import { NotebookNodeType } from 'scenes/notebooks/types'

import { NodeKind } from '~/queries/schema/schema-general'

import { notebookInsightDataframeLogic } from './notebookInsightDataframeLogic'

export async function prepareNotebookInsightDataframes(
    notebook: BuiltLogic<notebookLogicType>,
    names?: string[]
): Promise<void> {
    if (notebook.values.isShared || !notebook.values.canEditNotebook) {
        return
    }
    const candidates = collectNotebookDataframeNodes(notebook.values.content).filter(
        ({ node, returnVariable }) =>
            node.type === NotebookNodeType.Query &&
            isReferenceableSqlV2FrameName(returnVariable) &&
            (!names || names.includes(returnVariable))
    )
    for (const { node, nodeId } of candidates) {
        const attributes = node.attrs ?? {}
        const savedId =
            attributes.id ??
            (attributes.query?.kind === NodeKind.SavedInsightNode ? attributes.query.shortId : undefined)
        const logic = notebookInsightDataframeLogic({
            notebookLogic: notebook,
            nodeId,
            attributes,
            enabled: true,
            insightProps: savedId
                ? { dashboardItemId: savedId }
                : {
                      dashboardItemId: `new-AdHoc.notebook.${notebook.props.shortId}.${nodeId}`,
                      query: attributes.query,
                  },
            updateAttributes: (patch) => {
                const mountedNode = notebook.values.findNodeLogicById(nodeId)
                if (mountedNode) {
                    mountedNode.props.updateAttributes(patch)
                    return
                }
                const content = notebook.values.content
                const document = parseMarkdownNotebook(getMarkdownNotebookMarkdown(content))
                const index = document.nodes.findIndex(
                    (block) => block.type === 'component' && (block.props.nodeId || block.id) === nodeId
                )
                const block = document.nodes[index]
                if (!block || block.type !== 'component') {
                    throw new Error('The insight was removed from this notebook.')
                }
                document.nodes[index] = { ...block, props: { ...block.props, ...getSerializableProps(patch) } }
                notebook.actions.setLocalContent(
                    buildMarkdownNotebookContent(
                        serializeMarkdownNotebook(document),
                        getMarkdownNotebookNodeId(content)
                    )
                )
            },
        })
        const unmount = logic.mount()
        try {
            await logic.asyncActions.syncDataframe()
            if (logic.values.error && (!logic.values.unsupported || names)) {
                throw new Error(logic.values.error)
            }
        } finally {
            unmount()
        }
    }
}
