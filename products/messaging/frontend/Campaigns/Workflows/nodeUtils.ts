import { WorkflowEdgeData, WorkflowNodeData, WorkflowNodeType } from '@posthog/workflows'
import { Edge, Handle, Node, Position, XYPosition } from '@xyflow/react'

import { Optional } from '~/types'

import { ToolbarNode } from './WorkflowEditor'

export const NODE_WIDTH = 100
export const NODE_HEIGHT = 34

const TOP_HANDLE_POSITION = {
    x: NODE_WIDTH / 2,
    y: 0,
}

const BOTTOM_HANDLE_POSITION = {
    x: NODE_WIDTH / 2,
    y: NODE_HEIGHT,
}

const LEFT_HANDLE_POSITION = {
    x: 0,
    y: NODE_HEIGHT / 2,
}

const RIGHT_HANDLE_POSITION = {
    x: NODE_WIDTH,
    y: NODE_HEIGHT / 2,
}

export const getNodeHandles = (
    nodeId: string,
    nodeType: WorkflowNodeType
): Omit<Optional<Handle, 'width' | 'height'>, 'nodeId'>[] => {
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
                    ...LEFT_HANDLE_POSITION,
                },
                {
                    id: `${nodeId}_on_error`,
                    type: 'source',
                    position: Position.Right,
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
                    ...LEFT_HANDLE_POSITION,
                },
                {
                    id: `${nodeId}_on_error`, // The "else" edge
                    type: 'source',
                    position: Position.Right,
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
                    x: 0,
                    y: 0,
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
        }
    })
}

export const DEFAULT_EDGE_OPTIONS = {
    type: 'smoothstep',
    deletable: false,
    selectable: false,
}

export const DEFAULT_NODE_OPTIONS = {
    deletable: false,
    draggable: false,
    selectable: true,
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
    },
    {
        id: 'exit_node',
        type: 'exit',
        data: { label: 'Exit', description: '', config: null },
        handles: getNodeHandles('exit_node', 'exit'),
        position: { x: 0, y: 100 },
        ...DEFAULT_NODE_OPTIONS,
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

console.log({ DEFAULT_NODES, DEFAULT_EDGES })
