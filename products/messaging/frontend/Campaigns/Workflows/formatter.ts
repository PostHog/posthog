import { WorkflowNodeData } from '@posthog/workflows'
import { WorkflowEdgeData } from '@posthog/workflows'
import { Edge, Node, Position } from '@xyflow/react'
import ELK, { ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk.bundled.js'

const getElkPortSide = (position: Position): string => {
    switch (position) {
        case Position.Top:
            return 'NORTH'
        case Position.Bottom:
            return 'SOUTH'
        case Position.Left:
            return 'WEST'
        case Position.Right:
            return 'EAST'
    }
}

export const getFormattedNodes = async (
    nodes: Node<WorkflowNodeData>[],
    edges: Edge<WorkflowEdgeData>[]
): Promise<Node<WorkflowNodeData>[]> => {
    const elk = new ELK()

    const elkOptions = {
        'elk.algorithm': 'layered',
        'elk.layered.spacing.nodeNodeBetweenLayers': '100',
        'elk.spacing.nodeNode': '100',
        'elk.spacing.edgeEdge': '100',
        'elk.spacing.edgeNode': '100',
        'elk.direction': 'DOWN',
        'elk.alignment': 'CENTER',
        'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
    }

    const graph: ElkNode = {
        id: 'root',
        layoutOptions: elkOptions,
        children: nodes.map((node) => {
            const handles =
                node.handles?.map((h) => ({
                    id: h.id || `${node.id}_${h.type}`,
                    properties: {
                        side: getElkPortSide(h.position),
                    },
                })) || []

            return {
                ...node,
                width: 100,
                height: 34,
                properties: {
                    'org.eclipse.elk.portConstraints': 'FIXED_ORDER',
                },
                ports: [{ id: node.id }, ...handles],
            }
        }),
        edges: edges.map((edge) => ({
            ...edge,
            id: edge.id,
            sources: [edge.sourceHandle || edge.source],
            targets: [edge.targetHandle || edge.target],
        })) as ElkExtendedEdge[],
    }

    const layoutedGraph = await elk.layout(graph)

    return layoutedGraph.children?.map((node) => ({
        ...node,
        position: { x: node.x, y: node.y },
    })) as Node<WorkflowNodeData>[]
}
