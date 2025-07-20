import { lemonToast } from '@posthog/lemon-ui'
import {
    applyEdgeChanges,
    applyNodeChanges,
    EdgeChange,
    MarkerType,
    NodeChange,
    Position,
    ReactFlowInstance,
} from '@xyflow/react'
import { Edge, Node } from '@xyflow/react'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { uuid } from 'lib/utils'

import { campaignLogic, CampaignLogicProps } from '../campaignLogic'
import { BOTTOM_HANDLE_POSITION, TOP_HANDLE_POSITION } from './constants'
import type { hogFlowEditorLogicType } from './hogFlowEditorLogicType'
import { getHogFlowStep } from './steps/HogFlowSteps'
import { StepViewNodeHandle } from './steps/types'
import type { HogFlow, HogFlowAction, HogFlowActionNode } from './types'
import type { DragEvent } from 'react'

const getEdgeId = (edge: HogFlow['edges'][number]): string => `${edge.from}->${edge.to} ${edge.index ?? ''}`.trim()

export type HogFlowEditorMode = 'build' | 'test'

export const hogFlowEditorLogic = kea<hogFlowEditorLogicType>([
    props({} as CampaignLogicProps),
    path((key) => ['scenes', 'hogflows', 'hogFlowEditorLogic', key]),
    key((props) => `${props.id}`),
    connect((props: CampaignLogicProps) => ({
        values: [campaignLogic(props), ['campaign', 'edgesByActionId']],
        actions: [
            campaignLogic(props),
            ['setCampaignInfo', 'setCampaignActionConfig', 'setCampaignAction', 'setCampaignActionEdges'],
        ],
    })),
    actions({
        onEdgesChange: (edges: EdgeChange<Edge>[]) => ({ edges }),
        onNodesChange: (nodes: NodeChange<HogFlowActionNode>[]) => ({ nodes }),
        onNodesDelete: (deleted: HogFlowActionNode[]) => ({ deleted }),
        onEdgesDelete: (deleted: Edge[]) => ({ deleted }),
        setNodes: (nodes: HogFlowActionNode[]) => ({ nodes }),
        setEdges: (edges: Edge[]) => ({ edges }),
        setSelectedNodeId: (selectedNodeId: string | null) => ({ selectedNodeId }),
        resetFlowFromHogFlow: (hogFlow: HogFlow) => ({ hogFlow }),
        setReactFlowInstance: (reactFlowInstance: ReactFlowInstance<Node, Edge>) => ({
            reactFlowInstance,
        }),
        onDragStart: true,
        onDragOver: (event: DragEvent) => ({ event }),
        onDrop: (event: DragEvent) => ({ event }),
        onNodeDragStop: (_event: React.MouseEvent, node: HogFlowActionNode) => ({ node }),
        onConnect: ({ source, target }: { source: string; target: string }) => ({ source, target }),
        setNewDraggingNode: (newDraggingNode: HogFlowAction['type'] | null) => ({ newDraggingNode }),
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

        setCampaignActionEdges: () => {
            actions.resetFlowFromHogFlow(values.campaign)
        },
        setCampaignAction: () => {
            actions.resetFlowFromHogFlow(values.campaign)
        },
        setCampaignInfo: () => {
            actions.resetFlowFromHogFlow(values.campaign)
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
                    targetHandle: `target_${edge.to}`,
                    sourceHandle:
                        edge.type === 'continue' ? `continue_${edge.from}` : `branch_${edge.from}_${edge.index}`,
                }))

                const handlesByIdByNodeId: Record<string, Record<string, StepViewNodeHandle>> = {}

                hogFlow.actions.forEach((action: HogFlowAction) => {
                    if (!['trigger', 'exit'].includes(action.type)) {
                        const hasIncomingConnections = hogFlow.edges.some((edge) => edge.to === action.id)
                        const hasOutgoingConnections = hogFlow.edges.some((edge) => edge.from === action.id)

                        if (!hasIncomingConnections) {
                            if (!handlesByIdByNodeId[action.id]) {
                                handlesByIdByNodeId[action.id] = {}
                            }

                            handlesByIdByNodeId[action.id]['top'] = {
                                id: 'top',
                                type: 'target',
                                position: Position.Top,
                                ...TOP_HANDLE_POSITION,
                            }
                        }

                        if (!hasOutgoingConnections) {
                            if (!handlesByIdByNodeId[action.id]) {
                                handlesByIdByNodeId[action.id] = {}
                            }

                            handlesByIdByNodeId[action.id]['bottom'] = {
                                id: 'bottom',
                                type: 'source',
                                position: Position.Bottom,
                                ...BOTTOM_HANDLE_POSITION,
                            }
                        }
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
        },

        onNodeDragStop: ({ node }) => {
            // Update the position of the node in the campaign actions
            const originalAction = values.campaign.actions.find((action) => action.id === node.id)
            if (originalAction) {
                actions.setCampaignAction(node.id, { ...originalAction, position: node.position })
            }
        },

        onConnect: ({ source, target }) => {
            const newEdge: HogFlow['edges'][number] = {
                from: source,
                to: target,
                index: 0, // Default index, can be adjusted later
                type: 'branch',
            }

            const nodeEdges = values.edgesByActionId[target] || []

            actions.setCampaignActionEdges(target, [...nodeEdges, newEdge])
        },
    })),

    afterMount(({ actions, values }) => {
        // Initialize the flow with the current campaign data
        if (values.campaign) {
            actions.resetFlowFromHogFlow(values.campaign)
        }
    }),
])
