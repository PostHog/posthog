import { lemonToast } from '@posthog/lemon-ui'
import {
    applyEdgeChanges,
    applyNodeChanges,
    EdgeChange,
    getOutgoers,
    getSmoothStepPath,
    MarkerType,
    NodeChange,
    Position,
    ReactFlowInstance,
} from '@xyflow/react'
import { Edge, Node } from '@xyflow/react'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { uuid } from 'lib/utils'

import { campaignLogic, CampaignLogicProps } from '../campaignLogic'
import { getFormattedNodes } from './autolayout'
import { BOTTOM_HANDLE_POSITION, NODE_HEIGHT, NODE_WIDTH, TOP_HANDLE_POSITION } from './constants'
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
        setNodes: (nodes: HogFlowActionNode[]) => ({ nodes }),
        setDropzoneNodes: (dropzoneNodes: Node<{ edge: Edge }>[]) => ({ dropzoneNodes }),
        setNodesRaw: (nodes: HogFlowActionNode[]) => ({ nodes }),
        setEdges: (edges: Edge[]) => ({ edges }),
        setSelectedNodeId: (selectedNodeId: string | null) => ({ selectedNodeId }),
        resetFlowFromHogFlow: (hogFlow: HogFlow) => ({ hogFlow }),
        setReactFlowInstance: (reactFlowInstance: ReactFlowInstance<Node, Edge>) => ({
            reactFlowInstance,
        }),
        onDragStart: true,
        onDragOver: (event: DragEvent) => ({ event }),
        onDrop: (event: DragEvent) => ({ event }),
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
                setNodesRaw: (_, { nodes }) => nodes,
            },
        ],
        dropzoneNodes: [
            [] as Node<{ edge: Edge }>[],
            {
                setDropzoneNodes: (_, { dropzoneNodes }) => dropzoneNodes,
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
                    deletable: false,
                    reconnectable: false,
                    selectable: false,
                    focusable: false,
                    markerEnd: {
                        type: MarkerType.ArrowClosed,
                    },
                    labelShowBg: false,
                    targetHandle: `target_${edge.to}`,
                    sourceHandle:
                        edge.type === 'continue' ? `continue_${edge.from}` : `branch_${edge.from}_${edge.index}`,
                }))

                const handlesByIdByNodeId: Record<string, Record<string, StepViewNodeHandle>> = {}

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
                        position: { x: 0, y: 0 },
                        handles: Object.values(handlesByIdByNodeId[action.id] ?? {}),
                        deletable: !['trigger', 'exit'].includes(action.type),
                        selectable: true,
                        draggable: false,
                        connectable: false,
                    }
                })

                actions.setEdges(edges)
                actions.setNodes(nodes)
            } catch (error) {
                console.error('Error resetting flow from hog flow', error)
                lemonToast.error('Error updating workflow')
            }
        },

        setNodes: async ({ nodes }) => {
            const formattedNodes = await getFormattedNodes(nodes, values.edges)

            actions.setNodesRaw(formattedNodes)
        },

        onNodesDelete: ({ deleted }) => {
            if (deleted.some((node) => node.id === values.selectedNodeId)) {
                actions.setSelectedNodeId(null)
            }

            const deletedNodeIds = deleted.map((node) => node.id)

            // Find all edges connected to the deleted node then reconnect them to avoid orphaned nodes
            const updatedEdges = values.campaign.edges
                .map((hogFlowEdge) => {
                    if (deletedNodeIds.includes(hogFlowEdge.to)) {
                        // Find the deleted node
                        const deletedNode = deleted.find((node) => node.id === hogFlowEdge.to)
                        if (deletedNode) {
                            // Find the first outgoer of the deleted node
                            const outgoers = getOutgoers(deletedNode, values.nodes, values.edges)
                            if (outgoers.length > 0) {
                                // Change target to the first outgoer
                                return {
                                    ...hogFlowEdge,
                                    to: outgoers[0].id,
                                }
                            }
                        }
                    }
                    return hogFlowEdge
                })
                .filter(
                    (hogFlowEdge) =>
                        !deletedNodeIds.includes(hogFlowEdge.from) && !deletedNodeIds.includes(hogFlowEdge.to)
                )

            // Update campaign actions to match the new flow
            const updatedActions = values.campaign.actions.filter((action) => !deletedNodeIds.includes(action.id))

            actions.setCampaignInfo({ actions: updatedActions, edges: updatedEdges })
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

                    const [, labelX, labelY] = getSmoothStepPath({
                        sourceX: sourceNode.position.x + (sourceHandle?.x || 0),
                        sourceY: sourceNode.position.y + (sourceHandle?.y || 0),
                        targetX: targetNode.position.x + (targetHandle?.x || 0),
                        targetY: targetNode.position.y + (targetHandle?.y || 0),
                        sourcePosition: sourceHandle?.position || Position.Bottom,
                        targetPosition: targetHandle?.position || Position.Top,
                    })

                    dropzoneNodes.push({
                        id: `dropzone_edge_${edge.id}`,
                        type: 'dropzone',
                        position: { x: labelX - NODE_WIDTH / 2, y: labelY - NODE_HEIGHT / 2 },
                        data: {
                            edge,
                        },
                        draggable: false,
                        selectable: false,
                    })
                }
            })

            actions.setDropzoneNodes(dropzoneNodes)
        },

        onDragOver: ({ event }) => {
            event.preventDefault()
            event.dataTransfer.dropEffect = 'move'
        },

        onDrop: ({ event }) => {
            event.preventDefault()
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
            // We can clear the dropzones now
            actions.setDropzoneNodes([])
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
