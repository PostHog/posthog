import { lemonToast } from '@posthog/lemon-ui'
import {
    applyEdgeChanges,
    applyNodeChanges,
    Edge,
    EdgeChange,
    getSmoothStepPath,
    MarkerType,
    NodeChange,
    Position,
    ReactFlowInstance,
} from '@xyflow/react'
import { Node } from '@xyflow/react'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { uuid } from 'lib/utils'

import { campaignLogic, CampaignLogicProps } from '../campaignLogic'
import { BOTTOM_HANDLE_POSITION, NODE_WIDTH, TOP_HANDLE_POSITION } from './constants'
import type { hogFlowEditorLogicType } from './hogFlowEditorLogicType'
import { getHogFlowStep } from './steps/HogFlowSteps'
import { StepViewNodeHandle } from './steps/types'
import type { HogFlow, HogFlowAction, HogFlowActionNode } from './types'
import type { DragEvent } from 'react'
import { subscriptions } from 'kea-subscriptions'

const getEdgeId = (edge: HogFlow['edges'][number]): string =>
    `${edge.from}_${edge.type}${edge.index === undefined ? '' : `_${edge.index}`}->${edge.to}`.trim()

export type HogFlowEditorMode = 'build' | 'test'

export const hogFlowEditorLogic = kea<hogFlowEditorLogicType>([
    props({} as CampaignLogicProps),
    path((key) => ['scenes', 'hogflows', 'hogFlowEditorLogic', key]),
    key((props) => `${props.id}`),
    connect((props: CampaignLogicProps) => ({
        values: [campaignLogic(props), ['campaign', 'edgesByActionId']],
        actions: [
            campaignLogic(props),
            [
                'setCampaignInfo',
                'setCampaignActionConfig',
                'setCampaignAction',
                'setCampaignActionEdges',
                'setCampaignValues',
            ],
        ],
    })),
    actions({
        onEdgesChange: (edges: EdgeChange<Edge>[]) => ({ edges }),
        onNodesChange: (nodes: NodeChange<HogFlowActionNode>[]) => ({ nodes }),
        onNodesDelete: (deleted: HogFlowActionNode[]) => ({ deleted }),
        onEdgesDelete: (deleted: Edge[]) => ({ deleted }),
        setNodes: (nodes: HogFlowActionNode[]) => ({ nodes }),
        setDropzoneNodes: (dropzoneNodes: Node<{ edge: Edge }>[]) => ({ dropzoneNodes }),
        setEdgeDeletionNodes: (edgeDeletionNodes: Node<{ edge: Edge }>[]) => ({ edgeDeletionNodes }),
        deleteSelectedEdge: () => ({}),
        setEdges: (edges: Edge[]) => ({ edges }),
        setSelectedNodeId: (selectedNodeId: string | null) => ({ selectedNodeId }),
        setSelectedEdgeId: (selectedEdgeId: string | null) => ({ selectedEdgeId }),
        resetFlowFromHogFlow: (hogFlow: HogFlow) => ({ hogFlow }),
        setReactFlowInstance: (reactFlowInstance: ReactFlowInstance<Node, Edge>) => ({
            reactFlowInstance,
        }),
        onDragStart: true,
        onDragOver: (event: DragEvent) => ({ event }),
        onDrop: (event: DragEvent) => ({ event }),
        onNodeDragStart: () => ({}),
        onNodeDragStop: (_event: React.MouseEvent, node: HogFlowActionNode) => ({ node }),
        onConnect: ({
            source,
            target,
            sourceHandle,
            targetHandle,
        }: {
            source: string
            target: string
            sourceHandle: string | null
            targetHandle: string | null
        }) => ({ source, target, sourceHandle, targetHandle }),
        setNewDraggingNode: (newDraggingNode: HogFlowAction['type'] | null) => ({ newDraggingNode }),
        setHighlightedDropzoneNodeId: (highlightedDropzoneNodeId: string | null) => ({ highlightedDropzoneNodeId }),
        setMode: (mode: HogFlowEditorMode) => ({ mode }),
    }),
    reducers(() => ({
        mode: [
            'build' as HogFlowEditorMode,
            {
                setMode: (_, { mode }) => mode,
            },
        ],
        nodes: [
            [] as HogFlowActionNode[],
            {
                setNodes: (_, { nodes }) => nodes,
            },
        ],
        dropzoneNodes: [
            [] as Node<{ edge: Edge }>[],
            {
                setDropzoneNodes: (_, { dropzoneNodes }) => dropzoneNodes,
            },
        ],
        edgeDeletionNodes: [
            [] as Node<{ edge: Edge }>[],
            {
                setEdgeDeletionNodes: (_, { edgeDeletionNodes }) => edgeDeletionNodes,
            },
        ],
        highlightedDropzoneNodeId: [
            null as string | null,
            {
                setHighlightedDropzoneNodeId: (_, { highlightedDropzoneNodeId }) => highlightedDropzoneNodeId,
            },
        ],
        edges: [
            [] as Edge[],
            {
                setEdges: (_, { edges }) => edges,
            },
        ],
        selectedNodeId: [
            null as string | null,
            {
                setSelectedNodeId: (_, { selectedNodeId }) => selectedNodeId,
            },
        ],
        selectedEdgeId: [
            null as string | null,
            {
                setSelectedEdgeId: (_, { selectedEdgeId }) => selectedEdgeId,
            },
        ],

        newDraggingNode: [
            null as HogFlowAction['type'] | null,
            {
                setNewDraggingNode: (_, { newDraggingNode }) => newDraggingNode,
            },
        ],

        reactFlowInstance: [
            null as ReactFlowInstance<Node, Edge> | null,
            {
                setReactFlowInstance: (_, { reactFlowInstance }) => reactFlowInstance,
            },
        ],
    })),

    selectors({
        nodesById: [
            (s) => [s.nodes],
            (nodes): Record<string, HogFlowActionNode> => {
                return nodes.reduce((acc, node) => {
                    acc[node.id] = node
                    return acc
                }, {} as Record<string, HogFlowActionNode>)
            },
        ],
        selectedNode: [
            (s) => [s.nodes, s.selectedNodeId],
            (nodes, selectedNodeId) => {
                return nodes.find((node) => node.id === selectedNodeId) ?? null
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        onEdgesChange: ({ edges }) => {
            actions.setEdges(applyEdgeChanges(edges, values.edges))
        },
        onNodesChange: ({ nodes }) => {
            actions.setNodes(applyNodeChanges(nodes, values.nodes))
        },
        resetFlowFromHogFlow: ({ hogFlow }) => {
            try {
                const edges: Edge[] = hogFlow.edges.map((edge) => ({
                    // Only these values are set by the user
                    source: edge.from,
                    target: edge.to,

                    // All other values are derived
                    id: getEdgeId(edge),
                    type: 'smoothstep',
                    deletable: true,
                    reconnectable: true,
                    selectable: true,
                    focusable: true,
                    markerEnd: {
                        type: MarkerType.ArrowClosed,
                    },
                    labelShowBg: false,
                    targetHandle: 'target',
                    sourceHandle: edge.type === 'continue' ? `continue` : `branch_${edge.index}`,
                }))

                const handlesByIdByNodeId: Record<string, Record<string, StepViewNodeHandle>> = {}

                hogFlow.actions.forEach((action: HogFlowAction) => {
                    const hasIncomingConnections = Object.values(handlesByIdByNodeId[action.id] ?? {}).some(
                        (edge) => edge.type === 'target'
                    )

                    if (!hasIncomingConnections && action.type !== 'trigger') {
                        if (!handlesByIdByNodeId[action.id]) {
                            handlesByIdByNodeId[action.id] = {}
                        }

                        handlesByIdByNodeId[action.id]['target'] = {
                            id: 'target',
                            type: 'target',
                            position: Position.Top,
                            ...TOP_HANDLE_POSITION,
                        }
                    }

                    if (!['random_cohort_branch', 'exit'].includes(action.type)) {
                        if (!handlesByIdByNodeId[action.id]) {
                            handlesByIdByNodeId[action.id] = {}
                        }

                        handlesByIdByNodeId[action.id]['continue'] = {
                            id: 'continue',
                            type: 'source',
                            position: Position.Bottom,
                            ...BOTTOM_HANDLE_POSITION,
                        }
                    }
                    // For conditional_branch, add a handle for each condition
                    if (action.type === 'conditional_branch' && Array.isArray(action.config?.conditions)) {
                        action.config.conditions.forEach((_, idx) => {
                            handlesByIdByNodeId[action.id][`branch_${idx}`] = {
                                id: `branch_${idx}`,
                                type: 'source',
                                position: Position.Bottom,
                                ...BOTTOM_HANDLE_POSITION,
                            }
                        })
                    }
                    // For random_cohort, add a handle for each branch
                    if (action.type === 'random_cohort_branch' && Array.isArray(action.config?.cohorts)) {
                        action.config.cohorts.forEach((_, idx) => {
                            handlesByIdByNodeId[action.id][`branch_${idx}`] = {
                                id: `branch_${idx}`,
                                type: 'source',
                                position: Position.Bottom,
                                ...BOTTOM_HANDLE_POSITION,
                            }
                        })
                    }
                })

                edges.forEach((edge) => {
                    if (!handlesByIdByNodeId[edge.source]) {
                        handlesByIdByNodeId[edge.source] = {}
                    }
                    if (!handlesByIdByNodeId[edge.target]) {
                        handlesByIdByNodeId[edge.target] = {}
                    }

                    handlesByIdByNodeId[edge.source][edge.sourceHandle ?? ''] = {
                        id: edge.sourceHandle,
                        type: 'source',
                        position: Position.Bottom,
                        ...BOTTOM_HANDLE_POSITION,
                    }

                    handlesByIdByNodeId[edge.target][edge.targetHandle ?? ''] = {
                        id: edge.targetHandle,
                        type: 'target',
                        position: Position.Top,
                        ...TOP_HANDLE_POSITION,
                    }
                })

                const nodes: HogFlowActionNode[] = hogFlow.actions.map((action: HogFlowAction) => {
                    const step = getHogFlowStep(action.type)
                    if (!step) {
                        console.error(`Step not found for action type: ${action.type}`)
                        throw new Error(`Step not found for action type: ${action.type}`)
                    }

                    return {
                        id: action.id,
                        type: action.type,
                        data: action,
                        position: action.position ?? { x: 0, y: 0 },
                        handles: Object.values(handlesByIdByNodeId[action.id] ?? {}),
                        deletable: !['trigger', 'exit'].includes(action.type),
                        selectable: true,
                        draggable: true,
                        connectable: true,
                    }
                })

                actions.setEdges(edges)
                actions.setNodes(nodes)
            } catch (error) {
                console.error('Error resetting flow from hog flow', error)
                lemonToast.error('Error updating workflow')
            }
        },

        onNodesDelete: ({ deleted }) => {
            if (deleted.some((node) => node.id === values.selectedNodeId)) {
                actions.setSelectedNodeId(null)
            }

            actions.setCampaignInfo({
                actions: values.campaign.actions.filter((action) => !deleted.some((n) => n.id === action.id)),
            })
        },

        onDragStart: () => {
            const { nodes, edges } = values

            const dropzoneNodes: Node<{ edge: Edge }>[] = []

            edges.forEach((edge) => {
                const sourceNode = nodes.find((n) => n.id === edge.source)
                const targetNode = nodes.find((n) => n.id === edge.target)

                if (sourceNode && targetNode) {
                    const sourceHandle = sourceNode.handles?.find((h) => h.id === edge.sourceHandle)
                    const targetHandle = targetNode.handles?.find((h) => h.id === edge.targetHandle)

                    const [path] = getSmoothStepPath({
                        sourceX: sourceNode.position.x + (sourceHandle?.x || 0),
                        sourceY: sourceNode.position.y + (sourceHandle?.y || 0),
                        targetX: targetNode.position.x + (targetHandle?.x || 0),
                        targetY: targetNode.position.y + (targetHandle?.y || 0),
                        sourcePosition: sourceHandle?.position || Position.Bottom,
                        targetPosition: targetHandle?.position || Position.Top,
                    })

                    // Get point 10px down the path
                    const point = new DOMParser()
                        .parseFromString(
                            `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400" viewBox="0 0 124 124"><path d="${path}" /></svg>`,
                            'image/svg+xml'
                        )
                        .querySelector('path')
                        ?.getPointAtLength(20)

                    const labelX = point?.x || 0
                    const labelY = point?.y || 0

                    dropzoneNodes.push({
                        id: `dropzone_edge_${edge.id}`,
                        type: 'dropzone',
                        position: { x: labelX - NODE_WIDTH / 2, y: labelY },
                        data: {
                            edge,
                        },
                        draggable: false,
                        selectable: false,
                    })
                }
            })

            actions.setDropzoneNodes(dropzoneNodes)
            actions.setEdgeDeletionNodes([])
            actions.setSelectedEdgeId(null)
        },

        onEdgesDelete: ({ deleted }) => {
            actions.setCampaignInfo({
                edges: values.campaign.edges.filter((edge) => !deleted.some((e) => getEdgeId(edge) === e.id)),
            })
        },

        onDragOver: ({ event }) => {
            event.preventDefault()
            event.dataTransfer.dropEffect = 'move'
        },

        onDrop: ({ event }) => {
            event.preventDefault()

            // Drop node into dropzone edge if possible, otherwise insert with no connections at drop position
            const dropzoneNode = values.dropzoneNodes.find((x) => x.id === values.highlightedDropzoneNodeId)

            if (values.newDraggingNode && dropzoneNode) {
                const edgeToInsertNodeInto = dropzoneNode?.data.edge
                const step = getHogFlowStep(values.newDraggingNode)

                if (!step) {
                    throw new Error(`Step not found for action type: ${values.newDraggingNode}`)
                }

                const { action: partialNewAction, branchEdges = 0 } = step.create()

                const newAction = {
                    id: `action_${step.type}_${uuid()}`,
                    type: step.type,
                    created_at: Date.now(),
                    updated_at: Date.now(),
                    ...partialNewAction,
                    position: dropzoneNode.position,
                } as HogFlowAction

                const edgeToBeReplacedIndex = values.campaign.edges.findIndex(
                    (edge) => getEdgeId(edge) === edgeToInsertNodeInto.id
                )

                if (edgeToBeReplacedIndex === -1) {
                    throw new Error('Edge to be replaced not found')
                }

                // We add the new action with two new edges - the continue edge and the target edge
                // We also then check for any other missing edges based on the

                const newEdges: HogFlow['edges'] = [...values.campaign.edges]

                // First remove the edge to be replaced
                const edgeToBeReplaced = values.campaign.edges[edgeToBeReplacedIndex]

                newEdges.splice(edgeToBeReplacedIndex, 1)

                // Push the source edge first
                newEdges.push({
                    ...edgeToBeReplaced,
                    to: newAction.id,
                })

                // Then any branch edges
                for (let i = 0; i < branchEdges; i++) {
                    // Add in branching edges
                    newEdges.push({
                        ...edgeToBeReplaced,
                        index: i,
                        type: 'branch',
                        from: newAction.id,
                    })
                }

                // Finally the continue edge
                newEdges.push({
                    ...edgeToBeReplaced,
                    from: newAction.id,
                })

                const oldActions = values.campaign.actions
                const newActions = [...oldActions.slice(0, -1), newAction, oldActions[oldActions.length - 1]]

                actions.setCampaignInfo({ actions: newActions, edges: newEdges })
                actions.setNewDraggingNode(null)
                actions.setSelectedNodeId(newAction.id)
            }

            if (values.newDraggingNode) {
                const step = getHogFlowStep(values.newDraggingNode)
                if (!step) {
                    throw new Error(`Step not found for action type: ${values.newDraggingNode}`)
                }
                const { action: partialNewAction } = step.create()
                // Get drop position from React Flow event
                let position = { x: 0, y: 0 }
                const flowPosition = values.reactFlowInstance?.screenToFlowPosition({
                    x: event.clientX,
                    y: event.clientY,
                })
                if (flowPosition) {
                    position = flowPosition
                }
                const newAction = {
                    id: `action_${step.type}_${uuid()}`,
                    type: step.type,
                    created_at: Date.now(),
                    updated_at: Date.now(),
                    ...partialNewAction,
                    position,
                } as HogFlowAction
                // Add new node to actions
                const newActions = [...values.campaign.actions, newAction]
                actions.setCampaignInfo({ actions: newActions, edges: values.campaign.edges })
                actions.setNewDraggingNode(null)
                actions.setSelectedNodeId(newAction.id)
            }

            // We can clear the dropzones now
            actions.setDropzoneNodes([])
        },

        onNodeDragStart: () => {
            actions.setSelectedEdgeId(null)
            actions.setEdgeDeletionNodes([])
        },

        onNodeDragStop: ({ node }) => {
            actions.setCampaignAction(node.id, { ...node.data, position: node.position })
        },

        onConnect: ({ source, target, sourceHandle }) => {
            const newEdge: HogFlow['edges'][number] = {
                from: source,
                to: target,
                index: sourceHandle?.split('_')[1] === undefined ? undefined : Number(sourceHandle.split('_')[1]),
                type: sourceHandle?.split('_')[0] as HogFlow['edges'][number]['type'],
            }

            // Add the new edge to the campaign's edges array, preserving all other edges
            actions.setCampaignInfo({
                actions: values.campaign.actions,
                edges: [...values.campaign.edges, newEdge],
            })
        },

        setSelectedEdgeId: ({ selectedEdgeId }) => {
            const { nodes, edges } = values
            const selectedEdge = edges.find((edge) => edge.id === selectedEdgeId)
            if (!selectedEdge) {
                actions.setEdgeDeletionNodes([])
                return
            }

            const sourceNode = nodes.find((n) => n.id === selectedEdge.source)
            const targetNode = nodes.find((n) => n.id === selectedEdge.target)

            if (sourceNode && targetNode) {
                const sourceHandle = sourceNode.handles?.find((h) => h.id === selectedEdge.sourceHandle)
                const targetHandle = targetNode.handles?.find((h) => h.id === selectedEdge.targetHandle)

                const [, labelX, labelY] = getSmoothStepPath({
                    sourceX: sourceNode.position.x + (sourceHandle?.x || 0),
                    sourceY: sourceNode.position.y + (sourceHandle?.y || 0),
                    targetX: targetNode.position.x + (targetHandle?.x || 0),
                    targetY: targetNode.position.y + (targetHandle?.y || 0),
                    sourcePosition: sourceHandle?.position || Position.Bottom,
                    targetPosition: targetHandle?.position || Position.Top,
                })

                actions.setEdgeDeletionNodes([
                    {
                        id: `${selectedEdge.id}_deletion_button`,
                        type: 'edge_deletion_button',
                        position: { x: labelX - 8, y: labelY - 8 },
                        data: {
                            edge: selectedEdge,
                        },
                        draggable: false,
                        selectable: false,
                    },
                ])
            }
        },

        deleteSelectedEdge: () => {
            const selectedEdge = values.edges.find((edge) => edge.id === values.selectedEdgeId)
            if (selectedEdge) {
                actions.setSelectedEdgeId(null)
                actions.onEdgesDelete([selectedEdge])
            }
        },
    })),
    subscriptions(({ actions }) => ({
        campaign: (hogFlow?: HogFlow) => {
            if (hogFlow) {
                actions.resetFlowFromHogFlow(hogFlow)
            }
        },
    })),
])
