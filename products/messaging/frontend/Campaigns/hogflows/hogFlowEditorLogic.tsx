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

import { campaignLogic, CampaignLogicProps } from '../campaignLogic'
import { HogFlowActionManager } from './actions/hogFlowActionManager'
import { BaseHogFlowActionNode } from './actions/hogFlowActionManager'
import { getFormattedNodes } from './autolayout'
import { getDefaultNodeOptions, NODE_HEIGHT, NODE_WIDTH } from './constants'
import { getDefaultEdgeOptions } from './constants'
import type { hogFlowEditorLogicType } from './hogFlowEditorLogicType'
import { ToolbarNode } from './HogFlowEditorToolbar'
import type { HogFlow, HogFlowAction } from './types'

export const hogFlowEditorLogic = kea<hogFlowEditorLogicType>([
    props({} as CampaignLogicProps),
    path((key) => ['scenes', 'hogflows', 'hogFlowEditorLogic', key]),
    key((props) => `${props.id}`),
    connect((props: CampaignLogicProps) => ({
        values: [campaignLogic(props), ['campaign']],
        actions: [campaignLogic(props), ['setCampaignValues']],
    })),
    actions({
        onEdgesChange: (edges: EdgeChange<Edge>[]) => ({ edges }),
        onNodesChange: (nodes: NodeChange<Node<HogFlowAction>>[]) => ({ nodes }),
        onNodesDelete: (deleted: Node<HogFlowAction>[]) => ({ deleted }),
        setNodes: (nodes: Node<HogFlowAction>[]) => ({ nodes }),
        setDropzoneNodes: (dropzoneNodes: Node[]) => ({ dropzoneNodes }),
        setNodesRaw: (nodes: Node<HogFlowAction>[]) => ({ nodes }),
        setEdges: (edges: Edge[]) => ({ edges }),
        setSelectedNode: (selectedNode: Node<HogFlowAction> | undefined) => ({ selectedNode }),
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
            [] as Node<HogFlowAction>[],
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
        selectedNode: [
            undefined as Node<HogFlowAction> | undefined,
            {
                setSelectedNode: (_, { selectedNode }) => selectedNode,
            },
        ],

        newDraggingNode: [
            null as ToolbarNode | null,
            {
                setNewDraggingNode: (_, { newDraggingNode }) => newDraggingNode,
            },
        ],

        reactFlowInstance: [
            undefined as ReactFlowInstance<Node, Edge> | undefined,
            {
                setReactFlowInstance: (_, { reactFlowInstance }) => reactFlowInstance,
            },
        ],
    })),

    selectors({}),
    listeners(({ values, actions }) => ({
        onEdgesChange: ({ edges }) => {
            actions.setEdges(applyEdgeChanges(edges, values.edges))
        },
        onNodesChange: ({ nodes }) => {
            actions.setNodes(applyNodeChanges(nodes, values.nodes))
        },

        resetFlowFromHogFlow: ({ hogFlow }) => {
            const nodes = hogFlow.actions
                .map((action: HogFlowAction) => HogFlowActionManager.fromAction(action))
                .map((hogFlowAction: BaseHogFlowActionNode<HogFlowAction['type']>) => {
                    return {
                        id: hogFlowAction.action.id,
                        type: hogFlowAction.action.type,
                        data: hogFlowAction.action,
                        position: { x: 0, y: 0 },
                        handles: hogFlowAction.getHandles(),
                        ...getDefaultNodeOptions(['trigger', 'exit'].includes(hogFlowAction.action.type)),
                    }
                })
            const edges = hogFlow.actions.flatMap((action: HogFlowAction) =>
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
        },

        setNodes: async ({ nodes }) => {
            const formattedNodes = await getFormattedNodes(nodes)

            actions.setNodesRaw(formattedNodes)
        },
        onNodesDelete: ({ deleted }) => {
            if (deleted.some((node) => node.id === values.selectedNode?.id)) {
                actions.setSelectedNode(undefined)
            }

            const updatedActions = HogFlowActionManager.deleteActions(deleted, values.campaign)
            actions.setCampaignValues({ actions: updatedActions })
        },

        onDragStart: ({ event }) => {
            const { nodes, edges } = values
            // event.preventDefault()
            // event.dataTransfer.dropEffect = 'move'

            const dropzoneNodes: Node[] = []

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
            console.log('onDrop')
            event.preventDefault()

            const dropzoneNode = values.dropzoneNodes.find((x) => x.id === values.highlightedDropzoneNodeId)

            console.log('dropzoneNode', dropzoneNode)
            console.log('newDraggingNode', values.newDraggingNode)

            if (values.newDraggingNode && dropzoneNode) {
                // Create the new node in the position of the dropzone using the manager
                const updatedActions = HogFlowActionManager.insertNodeIntoDropzone(
                    values.campaign.actions,
                    values.newDraggingNode,
                    dropzoneNode
                )
                actions.setCampaignValues({ actions: updatedActions })
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
