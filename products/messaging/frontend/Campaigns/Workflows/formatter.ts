import { WorkflowNodeData } from '@posthog/workflows'
import { WorkflowEdgeData } from '@posthog/workflows'
import { Edge, Node } from '@xyflow/react'
import ELK, { ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk.bundled.js'

export const getFormattedNodes = async (
    nodes: Node<WorkflowNodeData>[],
    edges: Edge<WorkflowEdgeData>[]
): Promise<Node<WorkflowNodeData>[]> => {
    const elk = new ELK()

    const elkOptions = {
        'elk.algorithm': 'layered',
        'elk.layered.spacing.nodeNodeBetweenLayers': '60',
        'elk.spacing.nodeNode': '5',
        'elk.spacing.edgeEdge': '5',
        'elk.spacing.edgeNode': '5',
        'elk.direction': 'DOWN',
    }

    const graph: ElkNode = {
        id: 'root',
        layoutOptions: elkOptions,
        children: nodes.map((node) => ({
            ...node,
            targetPosition: 'top',
            sourcePosition: 'bottom',
            width: 100,
            height: 34,
        })),
        edges: edges.map((edge) => ({
            ...edge,
            id: edge.id,
            sources: [edge.source],
            targets: [edge.target],
            sourcePort: edge.data?.condition ? 'true' : undefined,
            targetPort: edge.data?.condition === false ? 'false' : undefined,
        })) as ElkExtendedEdge[],
    }

    const layoutedGraph = await elk.layout(graph)

    return layoutedGraph.children?.map((node) => ({
        ...node,
        position: { x: node.x, y: node.y },
    })) as Node<WorkflowNodeData>[]
}
