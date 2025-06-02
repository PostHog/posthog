import { Edge, getSmoothStepPath, Handle, Node, Position, XYPosition } from '@xyflow/react'

import { Optional } from '~/types'

import {
    BOTTOM_HANDLE_POSITION,
    DEFAULT_EDGE_OPTIONS,
    DEFAULT_NODE_OPTIONS,
    LEFT_HANDLE_POSITION,
    NODE_HEIGHT,
    NODE_WIDTH,
    RIGHT_HANDLE_POSITION,
    TOP_HANDLE_POSITION,
} from '../constants'
import { WorkflowEdgeData, WorkflowNodeData, WorkflowNodeType } from '../temporary_workflow_types_for_dev_to_be_deleted'
import { ToolbarNode } from '../Toolbar'

// When a new node is starting to be dragged into the workflow, show a dropzone node in the middle of every edge
export const addDropzoneNodes = (
    nodes: Node<WorkflowNodeData>[],
    edges: Edge<WorkflowEdgeData>[]
): Node<WorkflowNodeData>[] => {
    const newNodes = [...nodes]

    edges.forEach((edge) => {
        const sourceNode = nodes.find((n) => n.id === edge.source)
        const targetNode = nodes.find((n) => n.id === edge.target)

        if (sourceNode && targetNode) {
            const sourceHandle = sourceNode.handles?.find((h) => h.id === edge.sourceHandle)
            const targetHandle = targetNode.handles?.find((h) => h.id === edge.targetHandle)

            const [, labelX, labelY] = getSmoothStepPath({
                sourceX: sourceNode.position.x + (sourceHandle?.x || 0),
                sourceY: sourceNode.position.y + (sourceHandle?.y || 0),
                targetX: targetNode.position.x + (targetHandle?.x || 0),
                targetY: targetNode.position.y + (targetHandle?.y || 0),
                sourcePosition: sourceHandle?.position || Position.Bottom,
                targetPosition: targetHandle?.position || Position.Top,
            })

            const dropzoneId = `dropzone_edge_${edge.id}`
            newNodes.push({
                id: dropzoneId,
                type: 'dropzone',
                position: { x: labelX - NODE_WIDTH / 2, y: labelY - NODE_HEIGHT / 2 },
                data: { label: '', description: '', config: null },
                draggable: false,
                selectable: false,
            })
        }
    })

    return newNodes
}

type NodeHandle = Omit<Optional<Handle, 'width' | 'height'>, 'nodeId'> & { label?: string }
export const getNodeHandles = (nodeId: string, nodeType: WorkflowNodeType): NodeHandle[] => {
    switch (nodeType) {
        case 'trigger':
            return [
                {
                    id: `${nodeId}_source`,
                    type: 'source',
                    position: Position.Bottom,
                    ...BOTTOM_HANDLE_POSITION,
                },
            ]
        case 'exit':
            return [
                {
                    id: `${nodeId}_target`,
                    type: 'target',
                    position: Position.Top,
                    ...TOP_HANDLE_POSITION,
                },
            ]
        case 'email':
            return [
                {
                    id: `${nodeId}_target`,
                    type: 'target',
                    position: Position.Top,
                    ...TOP_HANDLE_POSITION,
                },
                {
                    id: `${nodeId}_on_success`,
                    type: 'source',
                    position: Position.Left,
                    label: 'Successful delivery',
                    ...LEFT_HANDLE_POSITION,
                },
                {
                    id: `${nodeId}_on_error`,
                    type: 'source',
                    position: Position.Right,
                    label: 'Delivery failed',
                    ...RIGHT_HANDLE_POSITION,
                },
            ]
        case 'delay_until':
            return [
                {
                    id: `${nodeId}_target`,
                    type: 'target',
                    position: Position.Top,
                    ...TOP_HANDLE_POSITION,
                },
                {
                    id: `${nodeId}_on_success`,
                    type: 'source',
                    position: Position.Left,
                    label: 'Match',
                    ...LEFT_HANDLE_POSITION,
                },
                {
                    id: `${nodeId}_on_error`,
                    type: 'source',
                    position: Position.Right,
                    label: 'Max checks reached',
                    ...RIGHT_HANDLE_POSITION,
                },
            ]
        case 'condition':
            return [
                {
                    id: `${nodeId}_target`,
                    type: 'target',
                    position: Position.Top,
                    ...TOP_HANDLE_POSITION,
                },
                {
                    id: `${nodeId}_on_match_condition_0`, // Start conditions with a single condition match edge
                    type: 'source',
                    position: Position.Left,
                    label: 'Match condition 1',
                    ...LEFT_HANDLE_POSITION,
                },
                {
                    id: `${nodeId}_on_error`, // The "else" edge
                    type: 'source',
                    position: Position.Right,
                    label: 'No match',
                    ...RIGHT_HANDLE_POSITION,
                },
            ]
        default:
            return [
                {
                    id: `${nodeId}_target`,
                    type: 'target',
                    position: Position.Top,
                    ...TOP_HANDLE_POSITION,
                },
                {
                    id: `${nodeId}_source`,
                    type: 'source',
                    position: Position.Bottom,
                    ...BOTTOM_HANDLE_POSITION,
                },
            ]
    }
}
export const createNewNode = (
    toolbarNode: ToolbarNode,
    nodeId?: string,
    position?: XYPosition
): Node<WorkflowNodeData> => {
    const id = nodeId || `${toolbarNode.type}_${Date.now()}`
    return {
        id,
        type: toolbarNode.type,
        data: {
            label: toolbarNode.label,
            description: '',
            config: null,
        },
        handles: getNodeHandles(id, toolbarNode.type),
        position: {
            x: position?.x || 0,
            y: position?.y || 0,
        },
        ...DEFAULT_NODE_OPTIONS,
    }
}

// Nodes that have multiple handles need to have edges created for each handle
export const createEdgesForNewNode = (
    nodeId: string,
    nodeType: WorkflowNodeType,
    edgeToInsertNodeInto: Edge<WorkflowEdgeData>
): Edge<WorkflowEdgeData>[] => {
    const handles = getNodeHandles(nodeId, nodeType)

    //TODO: change this to just use the incoming edge, and a single outgoing edge
    return handles.map((handle) => {
        // This is an incoming edge
        if (handle.type === 'target') {
            return {
                id: `${edgeToInsertNodeInto.source}->${nodeId}${handle.id ? `:${handle.id}` : ''}`,
                source: edgeToInsertNodeInto.source,
                target: nodeId,
                sourceHandle: edgeToInsertNodeInto.sourceHandle,
                targetHandle: handle.id,
                ...DEFAULT_EDGE_OPTIONS,
                label: edgeToInsertNodeInto?.label,
            }
        }
        // This is an outgoing edge
        return {
            id: `${nodeId}->${edgeToInsertNodeInto.target}${handle.id ? `:${handle.id}` : ''}`,
            source: nodeId,
            target: edgeToInsertNodeInto.target,
            sourceHandle: handle.id,
            targetHandle: edgeToInsertNodeInto.targetHandle,
            ...DEFAULT_EDGE_OPTIONS,
            label: handle.label,
        }
    })
}

// Initial node setup - just one starting node
export const DEFAULT_NODES: Node<WorkflowNodeData>[] = [
    {
        id: 'trigger_node',
        type: 'trigger',
        data: { label: 'Trigger', description: '', config: null },
        handles: getNodeHandles('trigger_node', 'trigger'),
        position: { x: 0, y: 0 },
        ...DEFAULT_NODE_OPTIONS,
        deletable: false,
    },
    {
        id: 'exit_node',
        type: 'exit',
        data: { label: 'Exit', description: '', config: null },
        handles: getNodeHandles('exit_node', 'exit'),
        position: { x: 0, y: 100 },
        ...DEFAULT_NODE_OPTIONS,
        selectable: false,
        deletable: false,
    },
]

// Initial edges setup
export const DEFAULT_EDGES: Edge<WorkflowEdgeData>[] = [
    {
        id: 'trigger_node->exit_node',
        source: 'trigger_node',
        sourceHandle: 'trigger_node_source',
        target: 'exit_node',
        targetHandle: 'exit_node_target',
        ...DEFAULT_EDGE_OPTIONS,
    },
]
