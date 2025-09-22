import {
    Edge,
    EdgeChange,
    MarkerType,
    Node,
    NodeChange,
    Position,
    ReactFlowInstance,
    applyEdgeChanges,
    applyNodeChanges,
    getOutgoers,
} from '@xyflow/react'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import type { DragEvent, RefObject } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { AppMetricsTotalsRequest, loadAppMetricsTotals } from 'lib/components/AppMetrics/appMetricsLogic'
import { uuid } from 'lib/utils'
import { urls } from 'scenes/urls'

import { optOutCategoriesLogic } from '../../OptOuts/optOutCategoriesLogic'
import { CampaignLogicProps, EXIT_NODE_ID, TRIGGER_NODE_ID, campaignLogic } from '../campaignLogic'
import { getFormattedNodes } from './autolayout'
import { BOTTOM_HANDLE_POSITION, NODE_HEIGHT, NODE_WIDTH, TOP_HANDLE_POSITION } from './constants'
import type { hogFlowEditorLogicType } from './hogFlowEditorLogicType'
import { getHogFlowStep } from './steps/HogFlowSteps'
import { getSmartStepPath } from './steps/SmartEdge'
import { StepViewNodeHandle } from './steps/types'
import type { HogFlow, HogFlowAction, HogFlowActionNode } from './types'

const getEdgeId = (edge: HogFlow['edges'][number]): string =>
    `${edge.from}->${edge.to} ${edge.type} ${edge.index ?? ''}`.trim()

export const HOG_FLOW_EDITOR_MODES = ['build', 'test', 'metrics', 'logs'] as const
export type HogFlowEditorMode = (typeof HOG_FLOW_EDITOR_MODES)[number]
export type HogFlowEditorActionMetrics = {
    actionId: string
    succeeded: number
    failed: number
    filtered: number
}

export type CreateActionType = Pick<HogFlowAction, 'type' | 'config' | 'name' | 'description'> & {
    branchEdges?: number
}

export const hogFlowEditorLogic = kea<hogFlowEditorLogicType>([
    props({} as CampaignLogicProps),
    path((key) => ['scenes', 'hogflows', 'hogFlowEditorLogic', key]),
    key((props) => `${props.id}`),
    connect((props: CampaignLogicProps) => ({
        values: [
            campaignLogic(props),
            ['campaign', 'edgesByActionId', 'hogFunctionTemplatesById'],
            optOutCategoriesLogic(),
            ['categories', 'categoriesLoading'],
        ],
        actions: [
            campaignLogic(props),
            ['setCampaignInfo', 'setCampaignAction', 'setCampaignActionEdges', 'loadCampaignSuccess'],
            optOutCategoriesLogic(),
            ['loadCategories'],
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
        setReactFlowWrapper: (reactFlowWrapper: RefObject<HTMLDivElement>) => ({ reactFlowWrapper }),
        onDragStart: true,
        onDragOver: (event: DragEvent) => ({ event }),
        onDrop: (event: DragEvent) => ({ event }),
        setNewDraggingNode: (newDraggingNode: CreateActionType | null) => ({ newDraggingNode }),
        setHighlightedDropzoneNodeId: (highlightedDropzoneNodeId: string | null) => ({ highlightedDropzoneNodeId }),
        setMode: (mode: HogFlowEditorMode) => ({ mode }),
        loadActionMetricsById: (
            params: Pick<AppMetricsTotalsRequest, 'appSource' | 'appSourceId' | 'dateFrom' | 'dateTo'>,
            timezone: string
        ) => ({ params, timezone }),
        fitView: (options: { duration?: number; noZoom?: boolean } = {}) => options,
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
            null as CreateActionType | null,
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
        reactFlowWrapper: [
            null as RefObject<HTMLDivElement> | null,
            {
                setReactFlowWrapper: (_, { reactFlowWrapper }) => reactFlowWrapper,
            },
        ],
    })),

    selectors({
        nodesById: [
            (s) => [s.nodes],
            (nodes): Record<string, HogFlowActionNode> => {
                return nodes.reduce(
                    (acc, node) => {
                        acc[node.id] = node
                        return acc
                    },
                    {} as Record<string, HogFlowActionNode>
                )
            },
        ],
        selectedNode: [
            (s) => [s.nodes, s.selectedNodeId],
            (nodes, selectedNodeId) => {
                return nodes.find((node) => node.id === selectedNodeId) ?? null
            },
        ],
        selectedNodeCanBeDeleted: [
            (s) => [s.selectedNode, s.nodes, s.edges],
            (selectedNode, nodes, edges) => {
                if (!selectedNode) {
                    return false
                }

                const outgoingNodes = getOutgoers(selectedNode, nodes, edges)
                if (outgoingNodes.length === 1) {
                    return true
                }

                return new Set(outgoingNodes.map((node) => node.id)).size === 1
            },
        ],
    }),
    loaders(() => ({
        actionMetricsById: [
            null as Record<string, HogFlowEditorActionMetrics> | null,
            {
                loadActionMetricsById: async ({ params, timezone }, breakpoint) => {
                    await breakpoint(10)
                    const _params: AppMetricsTotalsRequest = {
                        ...params,
                        breakdownBy: ['instance_id', 'metric_name'],
                        metricName: [
                            'succeeded',
                            'failed',
                            'filtered',
                            'disabled_permanently',
                            'rate_limited',
                            'triggered',
                        ],
                    }
                    const response = await loadAppMetricsTotals(_params, timezone)
                    await breakpoint(10)

                    const res: Record<string, HogFlowEditorActionMetrics> = {}
                    Object.values(response).forEach((value) => {
                        let [instanceId, metricName] = value.breakdowns

                        if (!metricName) {
                            return
                        }

                        if (!instanceId) {
                            // TRICKY: Trigger and exit dont get their own metrics so we pull from the overall metrics
                            if (['succeeded', 'failed'].includes(metricName)) {
                                instanceId = EXIT_NODE_ID
                            } else if (
                                ['filtered', 'disabled_permanently', 'rate_limited', 'triggered'].includes(metricName)
                            ) {
                                instanceId = TRIGGER_NODE_ID
                                if (['disabled_permanently', 'rate_limited'].includes(metricName)) {
                                    metricName = 'failed'
                                }
                                if (['triggered'].includes(metricName)) {
                                    metricName = 'succeeded'
                                }
                            }
                        }

                        res[instanceId] = res[instanceId] || {
                            actionId: instanceId,
                            succeeded: 0,
                            failed: 0,
                            filtered: 0,
                        }
                        if (metricName in res[instanceId]) {
                            ;(res[instanceId] as any)[metricName] = value.total
                        }
                    })

                    return res
                },
            },
        ],
    })),
    listeners(({ values, actions }) => ({
        onEdgesChange: ({ edges }) => {
            actions.setEdges(applyEdgeChanges(edges, values.edges))
        },
        onNodesChange: ({ nodes }) => {
            actions.setNodes(applyNodeChanges(nodes, values.nodes))
        },

        resetFlowFromHogFlow: ({ hogFlow }) => {
            try {
                const edges: Edge[] = hogFlow.edges.map((edge) => {
                    const isOnlyEdgeForNode = hogFlow.edges.filter((e) => e.from === edge.from).length === 1
                    const edgeSourceAction = hogFlow.actions.find((action) => action.id === edge.from)
                    const branchResourceName = () => {
                        switch (edgeSourceAction?.type) {
                            case 'wait_until_condition':
                                return 'condition'
                            case 'random_cohort_branch':
                                return `cohort #${(edge.index || 0) + 1}`
                            default:
                                return `condition #${(edge.index || 0) + 1}`
                        }
                    }

                    return {
                        // Only these values are set by the user
                        source: edge.from,
                        target: edge.to,

                        // All other values are derived
                        id: getEdgeId(edge),
                        type: 'smart',
                        deletable: false,
                        reconnectable: false,
                        selectable: false,
                        focusable: false,
                        markerEnd: {
                            type: MarkerType.ArrowClosed,
                        },
                        data: {
                            edge,
                            label: isOnlyEdgeForNode
                                ? undefined
                                : edge.type === 'continue'
                                  ? `No match`
                                  : `If ${branchResourceName()} matches`,
                        },
                        labelShowBg: false,
                        targetHandle: `target_${edge.to}`,
                        sourceHandle:
                            edge.type === 'continue' ? `continue_${edge.from}` : `branch_${edge.from}_${edge.index}`,
                    }
                })

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
                    const step = getHogFlowStep(action, values.hogFunctionTemplatesById)

                    if (!step) {
                        // Migrate old function actions to the basic functon action type
                        if (action.type.startsWith('function_')) {
                            action.type = 'function'
                        }
                    }

                    return {
                        id: action.id,
                        type: 'action',
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

                    const [, labelX, labelY] = getSmartStepPath({
                        sourceX: sourceNode.position.x + (sourceHandle?.x || 0),
                        sourceY: sourceNode.position.y + (sourceHandle?.y || 0),
                        targetX: targetNode.position.x + (targetHandle?.x || 0),
                        targetY: targetNode.position.y + (targetHandle?.y || 0),
                        edges,
                        currentEdgeId: edge.id,
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
                const partialNewAction = values.newDraggingNode

                const newAction = {
                    id: `action_${partialNewAction.type}_${uuid()}`,
                    type: partialNewAction.type,
                    name: partialNewAction.name,
                    description: partialNewAction.description,
                    config: partialNewAction.config,
                    created_at: Date.now(),
                    updated_at: Date.now(),
                } as HogFlowAction

                const step = getHogFlowStep(newAction, values.hogFunctionTemplatesById)

                const branchEdges = partialNewAction.branchEdges ?? 0

                if (!step) {
                    throw new Error(`Step not found for action type: ${newAction}`)
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
                    index: undefined,
                    type: 'continue',
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
        setReactFlowInstance: () => {
            // TRICKY: Slight race condition here where the react flow instance is not set yet
            setTimeout(() => {
                actions.fitView({ duration: 0 })
            }, 100)
        },
        setSelectedNodeId: ({ selectedNodeId }) => {
            if (selectedNodeId) {
                actions.fitView({ noZoom: true })
            }
        },
        fitView: ({ duration, noZoom }) => {
            const { reactFlowWrapper, reactFlowInstance } = values
            if (!reactFlowWrapper?.current || !reactFlowInstance) {
                return
            }
            // This is a rough estimate which we could improve by getting from the actual panel
            const PANEL_WIDTH = 580
            // Get the width of the wrapper
            const wrapperWidth = reactFlowWrapper.current.getBoundingClientRect()?.width ?? 0
            // Get the width of the thing we are going to fit to the view
            const nodesWidth =
                reactFlowInstance.getNodesBounds(values.selectedNode ? [values.selectedNode] : values.nodes)?.width ?? 0
            // Adjust the width for the zoom factor to be relative to the wrapper width
            const nodesWidthAdjusted = nodesWidth * reactFlowInstance.getZoom()
            // Calculate the padding right to fit the panel width to the wrapper width
            // Looks complicated but its basically the difference between the wrapper width and the nodes width adjusted for the zoom factor
            const paddingRight = wrapperWidth - nodesWidthAdjusted / 2 - (wrapperWidth - PANEL_WIDTH) / 2

            reactFlowInstance.fitView({
                padding: {
                    right: `${paddingRight}px`,
                },
                maxZoom: noZoom ? reactFlowInstance.getZoom() : undefined,
                minZoom: noZoom ? reactFlowInstance.getZoom() : undefined,
                nodes: values.selectedNode ? [values.selectedNode] : values.nodes,
                duration: duration ?? 100,
            })
        },
    })),

    subscriptions(({ actions }) => ({
        campaign: (hogFlow?: HogFlow) => {
            if (hogFlow) {
                actions.resetFlowFromHogFlow(hogFlow)
            }
        },
    })),

    actionToUrl(({ values }) => {
        const syncProperty = (
            key: string,
            value: string | null
        ): [string, Record<string, any>, Record<string, any>] => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    [key]: value,
                },
                router.values.hashParams,
            ]
        }

        return {
            setSelectedNodeId: () => syncProperty('node', values.selectedNodeId ?? null),
            setMode: () => syncProperty('mode', values.mode),
        }
    }),
    urlToAction(({ actions, values }) => {
        const reactToTabChange = (_: any, search: Record<string, string>): void => {
            const { node = null, mode } = search
            if (node !== values.selectedNodeId) {
                actions.setSelectedNodeId(node ?? null)
            }
            if (mode && HOG_FLOW_EDITOR_MODES.includes(mode as HogFlowEditorMode) && mode !== values.mode) {
                actions.setMode(mode as HogFlowEditorMode)
            }
        }

        return {
            [urls.messagingCampaign(':id', ':tab')]: reactToTabChange,
        }
    }),
])
