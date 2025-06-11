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
import { ToolbarNode } from '../Toolbar'
import type { HogFlowAction, HogFlowEdge } from '../types'

// When a new node is starting to be dragged into the workflow, show a dropzone node in the middle of every edge
export const addDropzoneNodes = (nodes: Node<HogFlowAction>[], edges: Edge<HogFlowEdge>[]): Node<HogFlowAction>[] => {
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
                data: {
                    id: dropzoneId,
                    name: 'Dropzone',
                    description: '',
                    type: 'delay',
                    config: null,
                    on_error: 'continue',
                    created_at: 0,
                    updated_at: 0,
                },
                draggable: false,
                selectable: false,
            })
        }
    })

    return newNodes
}

type NodeHandle = Omit<Optional<Handle, 'width' | 'height'>, 'nodeId'> & { label?: string }
export const getNodeHandles = (nodeId: string, nodeType: HogFlowAction['type']): NodeHandle[] => {
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
        case 'message':
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
        case 'wait_for_condition':
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
        case 'conditional_branch':
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
): Node<HogFlowAction> => {
    const id = nodeId || `${toolbarNode.type}_${Date.now()}`
    return {
        id,
        type: toolbarNode.type,
        data: {
            id,
            name: toolbarNode.name,
            description: '',
            config: null,
            type: toolbarNode.type,
            on_error: 'continue',
            created_at: 0,
            updated_at: 0,
        },
        handles: getNodeHandles(id, toolbarNode.type),
        position: {
            x: position?.x || 0,
            y: position?.y || 0,
        },
        ...DEFAULT_NODE_OPTIONS,
    }
}

export const createEdgesForNewNode = (
    nodeId: string,
    nodeType: HogFlowAction['type'],
    edgeToInsertNodeInto: Edge<HogFlowEdge>
): Edge<HogFlowEdge>[] => {
    const handles = getNodeHandles(nodeId, nodeType)

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

export const DEFAULT_NODES: Node<HogFlowAction>[] = [
    {
        id: 'trigger_node',
        type: 'trigger',
        data: {
            id: 'trigger_node',
            name: 'Trigger',
            type: 'trigger',
            description: '',
            config: null,
            created_at: 0,
            updated_at: 0,
        },
        handles: getNodeHandles('trigger_node', 'trigger'),
        position: { x: 0, y: 0 },
        ...DEFAULT_NODE_OPTIONS,
        deletable: false,
    },
    {
        id: 'exit_node',
        type: 'exit',
        data: {
            id: 'exit_node',
            name: 'Exit',
            type: 'exit',
            description: '',
            config: null,
            created_at: 0,
            updated_at: 0,
        },
        handles: getNodeHandles('exit_node', 'exit'),
        position: { x: 0, y: 100 },
        ...DEFAULT_NODE_OPTIONS,
        selectable: false,
        deletable: false,
    },
]

export const DEFAULT_EDGES: Edge<HogFlowEdge>[] = [
    {
        id: 'trigger_node->exit_node',
        source: 'trigger_node',
        sourceHandle: 'trigger_node_source',
        target: 'exit_node',
        targetHandle: 'exit_node_target',
        ...DEFAULT_EDGE_OPTIONS,
    },
]
