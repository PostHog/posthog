import { buildNotebookDependencyGraph, collectDependencyNodeIds } from 'scenes/notebooks/Nodes/notebookNodeContent'
import { buildMarkdownNotebookContent } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { NotebookNodeType } from 'scenes/notebooks/types'

export function privateWidgetSourceNames(markdown: string): Set<string> {
    const graph = buildNotebookDependencyGraph(buildMarkdownNotebookContent(markdown))
    const privateSources = new Set<string>()
    for (const node of graph.nodes) {
        if (node.nodeType === NotebookNodeType.PythonV2 || node.connectionId) {
            for (const id of collectDependencyNodeIds(graph, node.nodeId, 'downstream')) {
                for (const name of graph.nodesById[id].exports) {
                    privateSources.add(name)
                }
            }
        }
    }
    return privateSources
}
