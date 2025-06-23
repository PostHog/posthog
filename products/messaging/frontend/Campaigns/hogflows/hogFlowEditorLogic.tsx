import { lemonToast } from '@posthog/lemon-ui'
import {
    applyEdgeChanges,
    applyNodeChanges,
    EdgeChange,
    getSmoothStepPath,
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
import { NODE_HEIGHT, NODE_WIDTH } from './constants'
import { getDefaultEdgeOptions } from './constants'
import type { hogFlowEditorLogicType } from './hogFlowEditorLogicType'
import { ToolbarNode } from './HogFlowEditorToolbar'
import { getHogFlowStep } from './steps/HogFlowSteps'
import type { HogFlow, HogFlowAction } from './types'

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
        onNodesChange: (nodes: NodeChange<Node<HogFlowAction>>[]) => ({ nodes }),
        onNodesDelete: (deleted: Node<HogFlowAction>[]) => ({ deleted }),
        setNodes: (nodes: Node<HogFlowAction>[]) => ({ nodes }),
        setDropzoneNodes: (dropzoneNodes: Node<{ edge: Edge }>[]) => ({ dropzoneNodes }),
        setNodesRaw: (nodes: Node<HogFlowAction>[]) => ({ nodes }),
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
    reducers(({ props }) => ({
        nodes: [
            [] as Node<HogFlowAction>[],
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
                const nodes: Node<HogFlowAction>[] = hogFlow.actions.map((action: HogFlowAction) => {
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
                        handles: step.getHandles(action),
                        deletable: !['trigger', 'exit'].includes(action.type),
                        selectable: true,
                        draggable: false,
                        connectable: false,
                    }
                })

                const edges: Edge[] = hogFlow.actions.flatMap((action: HogFlowAction) =>
                    Object.entries(action.next_actions).map(([branch, next_action]) => ({
                        id: `${branch}_${action.id}->${next_action.action_id}`,
                        label: next_action.label,
                        source: action.id,
                        sourceHandle: `${branch}_${action.id}`,
                        target: next_action.action_id,
                        targetHandle: `target_${next_action.action_id}`,
                        ...getDefaultEdgeOptions(),
                    }))
                )

                actions.setNodes(nodes)
                actions.setEdges(edges)
            } catch (error) {
                console.error('Error resetting flow from hog flow', error)
                lemonToast.error('Error updating workflow')
            }
        },

        setNodes: async ({ nodes }) => {
            const formattedNodes = await getFormattedNodes(nodes)

            actions.setNodesRaw(formattedNodes)
        },
        onNodesDelete: ({ deleted }) => {
            if (deleted.some((node) => node.id === values.selectedNodeId)) {
                actions.setSelectedNodeId(null)
            }

            const deletedNodeIds = deleted.map((node) => node.id)
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

                // TRICKY: Typing is a bit weird here...
                const newAction: HogFlowAction = {
                    id: `action_${step.type}_${uuid()}`,
                    type: step.type,
                    created_at: Date.now(),
                    updated_at: Date.now(),
                    ...step.create(edgeToInsertNodeInto),
                }

                const edgeSourceNode = values.campaign.actions.find(
                    (action) => action.id === edgeToInsertNodeInto.source
                )

                if (!edgeSourceNode) {
                    throw new Error('Edge source node not found')
                }

                Object.keys(edgeSourceNode.next_actions).forEach((key) => {
                    edgeSourceNode.next_actions[key] = {
                        action_id: newAction.id,
                        label: edgeSourceNode.next_actions[key].label,
                    }
                })

                const oldActions = values.campaign.actions
                const newActions = [...oldActions.slice(0, -1), newAction, oldActions[oldActions.length - 1]]

                actions.setCampaignValues({ actions: newActions })
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
