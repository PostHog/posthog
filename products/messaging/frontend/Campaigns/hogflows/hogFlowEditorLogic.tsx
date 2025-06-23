import { lemonToast } from '@posthog/lemon-ui'
import {
    applyEdgeChanges,
    applyNodeChanges,
    EdgeChange,
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
import { ToolbarNode } from './HogFlowEditorToolbar'
import { getHogFlowStep } from './steps/HogFlowSteps'
import { StepViewNodeHandle } from './steps/types'
import type { HogFlow, HogFlowAction, HogFlowActionNode } from './types'

const getEdgeId = (edge: HogFlow['edges'][number]) => `${edge.from}->${edge.to} ${edge.index ?? ''}`.trim()

export const hogFlowEditorLogic = kea<hogFlowEditorLogicType>([
    props({} as CampaignLogicProps),
    path((key) => ['scenes', 'hogflows', 'hogFlowEditorLogic', key]),
    key((props) => `${props.id}`),
    connect((props: CampaignLogicProps) => ({
        values: [campaignLogic(props), ['campaign']],
        actions: [campaignLogic(props), ['setCampaignValues', 'setCampaignActionConfig', 'setCampaignAction']],
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
        onDragOver: (event: React.DragEvent) => ({ event }),
        onDrop: (event: React.DragEvent) => ({ event }),
        setNewDraggingNode: (newDraggingNode: ToolbarNode | null) => ({ newDraggingNode }),
        setHighlightedDropzoneNodeId: (highlightedDropzoneNodeId: string | null) => ({ highlightedDropzoneNodeId }),
    }),
    reducers(() => ({
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
            null as ToolbarNode | null,
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
            (nodes) => {
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

                const handlesByNodeId: Record<string, StepViewNodeHandle[]> = {}

                edges.forEach((edge) => {
                    if (!handlesByNodeId[edge.source]) {
                        handlesByNodeId[edge.source] = []
                    }
                    if (!handlesByNodeId[edge.target]) {
                        handlesByNodeId[edge.target] = []
                    }

                    handlesByNodeId[edge.source].push({
                        id: edge.sourceHandle,
                        type: 'source',
                        position: Position.Bottom,
                        ...BOTTOM_HANDLE_POSITION,
                    })

                    handlesByNodeId[edge.target].push({
                        id: edge.targetHandle,
                        type: 'target',
                        position: Position.Top,
                        ...TOP_HANDLE_POSITION,
                    })
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
                        handles: handlesByNodeId[action.id],
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

            // Find all edges connected to the deleted nodes.
            // All edges that are connected to the deleted node should be deleted and replaced with an edge to the original node.

            const updatedActions = values.campaign.actions
                .filter((action) => !deletedNodeIds.includes(action.id))
                .map((action) => {
                    // For each action, update its next_actions to skip deleted nodes
                    const updatedNextActions: Record<string, { action_id: string; label?: string }> = {}

                    Object.entries(action.next_actions).forEach(([branch, nextAction]) => {
                        if (deletedNodeIds.includes(nextAction.action_id)) {
                            // Find the deleted node's continue action and use that instead
                            const deletedNode = values.campaign.actions.find((a) => a.id === nextAction.action_id)
                            if (deletedNode?.next_actions.continue) {
                                updatedNextActions[branch] = {
                                    action_id: deletedNode.next_actions.continue.action_id,
                                    label:
                                        action.type === deletedNode.type
                                            ? deletedNode.next_actions.continue.label
                                            : undefined,
                                }
                            }
                        } else {
                            updatedNextActions[branch] = nextAction
                        }
                    })

                    return {
                        ...action,
                        next_actions: updatedNextActions,
                    }
                })

            actions.setCampaignValues({ actions: updatedActions })
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
                const step = getHogFlowStep(values.newDraggingNode.type)

                if (!step) {
                    throw new Error(`Step not found for action type: ${values.newDraggingNode.type}`)
                }

                const { action: partialNewAction, branchEdges = 0 } = step.create()
                // TRICKY: Typing is a bit weird here...
                const newAction: HogFlowAction = {
                    id: `action_${step.type}_${uuid()}`,
                    type: step.type,
                    created_at: Date.now(),
                    updated_at: Date.now(),
                    ...partialNewAction,
                }

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

                console.log('Edges before', [...newEdges])
                newEdges.splice(edgeToBeReplacedIndex, 1)

                // Now add the new edges for the new action
                newEdges.push({
                    ...edgeToBeReplaced,
                    from: newAction.id,
                })

                newEdges.push({
                    ...edgeToBeReplaced,
                    to: newAction.id,
                })

                // for (let i = 0; i < branchEdges; i++) {
                //     // Add in branching edges
                //     newEdges.push({
                //         ...edgeToBeReplaced,
                //         index: i,
                //         type: 'branch',
                //         from: newAction.id,
                //     })
                // }

                console.log('Edges after', [...newEdges])

                const oldActions = values.campaign.actions
                const newActions = [...oldActions.slice(0, -1), newAction, oldActions[oldActions.length - 1]]

                actions.setCampaignValues({ actions: newActions, edges: newEdges })
                actions.setNewDraggingNode(null)
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
