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
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import type { DragEvent, RefObject } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { AppMetricsTotalsRequest, loadAppMetricsTotals } from 'lib/components/AppMetrics/appMetricsLogic'
import { uuid } from 'lib/utils'
import { urls } from 'scenes/urls'

import { optOutCategoriesLogic } from '../../OptOuts/optOutCategoriesLogic'
import { EXIT_NODE_ID, TRIGGER_NODE_ID, WorkflowLogicProps, workflowLogic } from '../workflowLogic'
import type { hogFlowEditorLogicType } from './hogFlowEditorLogicType'
import { getSmartStepPath } from './react_flow_utils/SmartEdge'
import { getFormattedNodes } from './react_flow_utils/autolayout'
import { BOTTOM_HANDLE_POSITION, NODE_HEIGHT, NODE_WIDTH, TOP_HANDLE_POSITION } from './react_flow_utils/constants'
import { getHogFlowStep } from './steps/HogFlowSteps'
import { StepViewNodeHandle } from './steps/types'
import type { DropzoneNode, HogFlow, HogFlowAction, HogFlowActionEdge, HogFlowActionNode } from './types'

const getEdgeId = (edge: HogFlow['edges'][number]): string =>
    `${edge.from}->${edge.to} ${edge.type} ${edge.index ?? ''}`.trim()

/**
 * Helper to get branch label with custom name fallback
 */
const getBranchLabel = (action: HogFlowAction | undefined, edge: HogFlow['edges'][0]): string => {
    if (!action) {
        return `If condition #${(edge.index || 0) + 1} matches`
    }

    switch (action.type) {
        case 'wait_until_condition': {
            const waitAction = action as Extract<HogFlowAction, { type: 'wait_until_condition' }>
            const customName = waitAction.config.condition?.name
            return customName || 'If condition matches'
        }
        case 'random_cohort_branch': {
            const cohortAction = action as Extract<HogFlowAction, { type: 'random_cohort_branch' }>
            const cohort = cohortAction.config.cohorts?.[edge.index || 0]
            return cohort?.name || `If cohort #${(edge.index || 0) + 1} matches`
        }
        case 'conditional_branch': {
            const branchAction = action as Extract<HogFlowAction, { type: 'conditional_branch' }>
            const condition = branchAction.config.conditions?.[edge.index || 0]
            return condition?.name || `If condition #${(edge.index || 0) + 1} matches`
        }
        default:
            return `If condition #${(edge.index || 0) + 1} matches`
    }
}

export const HOG_FLOW_EDITOR_MODES = ['build', 'variables', 'test', 'metrics', 'logs'] as const
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
    props({} as WorkflowLogicProps),
    path((key) => ['scenes', 'hogflows', 'hogFlowEditorLogic', key]),
    key((props) => `${props.id}`),
    connect((props: WorkflowLogicProps) => ({
        values: [
            workflowLogic(props),
            ['workflow', 'edgesByActionId', 'hogFunctionTemplatesById'],
            optOutCategoriesLogic(),
            ['categories', 'categoriesLoading'],
        ],
        actions: [
            workflowLogic(props),
            ['setWorkflowInfo', 'setWorkflowAction', 'setWorkflowActionEdges', 'loadWorkflowSuccess'],
            optOutCategoriesLogic(),
            ['loadCategories'],
        ],
    })),
    actions({
        onEdgesChange: (edges: EdgeChange<HogFlowActionEdge>[]) => ({ edges }),
        onNodesChange: (nodes: NodeChange<HogFlowActionNode>[]) => ({ nodes }),
        onNodesDelete: (deleted: HogFlowActionNode[]) => ({ deleted }),
        setNodes: (nodes: HogFlowActionNode[]) => ({ nodes }),
        setDropzoneNodes: (dropzoneNodes: DropzoneNode[]) => ({
            dropzoneNodes,
        }),
        showDropzones: true,
        hideDropzones: true,
        setNodesRaw: (nodes: HogFlowActionNode[]) => ({ nodes }),
        setEdges: (edges: HogFlowActionEdge[]) => ({ edges }),
        setSelectedNodeId: (selectedNodeId: string | null) => ({ selectedNodeId }),
        resetFlowFromHogFlow: (hogFlow: HogFlow) => ({ hogFlow }),
        setReactFlowInstance: (reactFlowInstance: ReactFlowInstance<Node, Edge>) => ({
            reactFlowInstance,
        }),
        setReactFlowWrapper: (reactFlowWrapper: RefObject<HTMLDivElement>) => ({ reactFlowWrapper }),
        onDragOver: (event: DragEvent) => ({ event }),
        onDrop: (event?: DragEvent) => ({ event }),
        setNodeToBeAdded: (nodeToBeAdded: CreateActionType | HogFlowActionNode | null) => ({ nodeToBeAdded }),
        setHighlightedDropzoneNodeId: (highlightedDropzoneNodeId: string | null) => ({ highlightedDropzoneNodeId }),
        setMode: (mode: HogFlowEditorMode) => ({ mode }),
        startCopyingNode: (node: HogFlowActionNode) => ({ node }),
        stopCopyingNode: true,
        copyNodeToHighlightedDropzone: true,
        loadActionMetricsById: (
            params: Pick<AppMetricsTotalsRequest, 'appSource' | 'appSourceId' | 'dateFrom' | 'dateTo'>,
            timezone: string
        ) => ({ params, timezone }),
        fitView: (options: { duration?: number; noZoom?: boolean } = {}) => options,
        handlePaneClick: true,
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
            [] as DropzoneNode[],
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
            [] as HogFlowActionEdge[],
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
        isCopyingNode: [
            false,
            {
                startCopyingNode: () => true,
                stopCopyingNode: () => false,
            },
        ],
        nodeToBeAdded: [
            null as CreateActionType | HogFlowActionNode | null,
            {
                setNodeToBeAdded: (_, { nodeToBeAdded }) => nodeToBeAdded,
                startCopyingNode: (_, { node }) => node.data,
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
                const edges: HogFlowActionEdge[] = hogFlow.edges.map((edge) => {
                    const isOnlyEdgeForNode = hogFlow.edges.filter((e) => e.from === edge.from).length === 1
                    const edgeSourceAction = hogFlow.actions.find((action) => action.id === edge.from)

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
                                  : getBranchLabel(edgeSourceAction, edge),
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
            const updatedEdges = values.workflow.edges
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

            // Update workflow actions to match the new flow
            const updatedActions = values.workflow.actions.filter((action) => !deletedNodeIds.includes(action.id))

            actions.setWorkflowInfo({ actions: updatedActions, edges: updatedEdges })
        },

        showDropzones: () => {
            const { nodes, edges } = values

            const dropzoneNodes: DropzoneNode[] = []

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

                    // If this branch edge has same target as other edges, we also add a single dropzone near the target node
                    const hasSiblingEdges = edges.filter((e) => e.data?.edge.to === edge.target).length > 1
                    if (edge.data?.edge.type === 'branch' && hasSiblingEdges) {
                        // Use an ID that we can consistently look up for the branch join point to avoid duplicate dropzones
                        const branchJoinDropzoneTargetId = `dropzone_target_${edge.target}_branch_join`
                        // Avoid duplicating dropzones for multiple branch edges to the same target
                        if (dropzoneNodes.find((n) => n.id === branchJoinDropzoneTargetId)) {
                            return
                        }

                        // For branch edges, we also add a dropzone near the target node to allow easier dropping
                        dropzoneNodes.push({
                            id: branchJoinDropzoneTargetId,
                            type: 'dropzone',
                            position: {
                                x: targetNode.position.x,
                                y: targetNode.position.y - NODE_HEIGHT,
                            },
                            data: {
                                edge,
                                isBranchJoinDropzone: true,
                            },
                            draggable: false,
                            selectable: false,
                        })
                    }
                }
            })

            actions.setDropzoneNodes(dropzoneNodes)
        },

        hideDropzones: () => {
            actions.setDropzoneNodes([])
        },

        onDragOver: ({ event }) => {
            event.preventDefault()
            event.dataTransfer.dropEffect = 'move'
        },

        onDrop: ({ event }) => {
            event?.preventDefault()
            const dropzoneNode = values.dropzoneNodes.find((x) => x.id === values.highlightedDropzoneNodeId)

            if (values.nodeToBeAdded && dropzoneNode) {
                const edgeToInsertNodeInto = dropzoneNode?.data.edge

                // Check if nodeToBeAdded is a HogFlowActionNode (has 'data' property) or CreateActionType
                const isHogFlowActionNode = 'data' in values.nodeToBeAdded
                const partialNewAction = isHogFlowActionNode
                    ? (values.nodeToBeAdded as HogFlowActionNode).data
                    : (values.nodeToBeAdded as CreateActionType)

                const newAction = {
                    id: isHogFlowActionNode
                        ? (values.nodeToBeAdded as HogFlowActionNode).id
                        : `action_${partialNewAction.type}_${uuid()}`,
                    type: partialNewAction.type,
                    name: partialNewAction.name,
                    description: partialNewAction.description,
                    config: partialNewAction.config,
                    created_at: Date.now(),
                    updated_at: Date.now(),
                } as HogFlowAction

                const step = getHogFlowStep(newAction, values.hogFunctionTemplatesById)

                const branchEdges = isHogFlowActionNode ? 0 : ((partialNewAction as CreateActionType).branchEdges ?? 0)
                const isBranchJoinDropzone = dropzoneNode?.data.isBranchJoinDropzone ?? false

                if (!step) {
                    throw new Error(`Step not found for action type: ${newAction}`)
                }

                let edgesToBeReplacedIndexes = []

                if (isBranchJoinDropzone) {
                    // There are multiple edges that need to be replaced here to join the branches on new node

                    /**
                     * If isBranchJoinDropzone is set, we know to connect this new node on top with all previous target's sources
                     * and below with the original edges' shared target
                     */
                    edgesToBeReplacedIndexes = values.workflow.edges
                        .map((edge, index) => ({
                            edge,
                            index,
                        }))
                        .filter(({ edge }) => edge.to === edgeToInsertNodeInto.target)
                        .map(({ index }) => index)
                } else {
                    // There is just the one *very specific* (i.e. getEdgeId must be used) target edge that needs to be replaced
                    edgesToBeReplacedIndexes = [
                        values.workflow.edges.findIndex((edge) => getEdgeId(edge) === edgeToInsertNodeInto.id),
                    ]
                }

                if (edgesToBeReplacedIndexes.length === 0) {
                    throw new Error('Edge to be replaced not found')
                }

                // We add the new action with two new edges - the continue edge and the target edge
                // We also then check for any other missing edges based on the type of edge being replaced

                const newEdges: HogFlow['edges'] = [...values.workflow.edges]

                // First remove the edge to be replaced
                const edgesToBeReplaced = edgesToBeReplacedIndexes.map((index) => values.workflow.edges[index])

                // Sort indexes in descending order to avoid index shifting during removal
                edgesToBeReplacedIndexes
                    .sort((a, b) => b - a)
                    .forEach((index) => {
                        newEdges.splice(index, 1)
                    })

                for (const edgeToBeReplaced of edgesToBeReplaced) {
                    // Push the source edge first
                    newEdges.push({
                        ...edgeToBeReplaced,
                        to: newAction.id,
                    })
                }

                // Then any branch edges (once, not per incoming edge)
                for (let i = 0; i < branchEdges; i++) {
                    // Add in branching edges
                    newEdges.push({
                        ...edgesToBeReplaced[0],
                        index: i,
                        type: 'branch',
                        from: newAction.id,
                    })
                }

                // Finally the last continue edge
                newEdges.push({
                    ...edgesToBeReplaced[0],
                    index: undefined,
                    type: 'continue',
                    from: newAction.id,
                })

                const oldActions = values.workflow.actions
                const newActions = [...oldActions.slice(0, -1), newAction, oldActions[oldActions.length - 1]]

                actions.setWorkflowInfo({ actions: newActions, edges: newEdges })
                actions.setNodeToBeAdded(null)
                actions.setSelectedNodeId(newAction.id)
            }
            // We can clear the dropzones now
            actions.hideDropzones()
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
        startCopyingNode: () => {
            actions.showDropzones()
        },
        stopCopyingNode: () => {
            actions.hideDropzones()
        },
        copyNodeToHighlightedDropzone: () => {
            // Copy action, move to new spot
            actions.onDrop()
            // Clear moving node ID
            actions.stopCopyingNode()
        },
        handlePaneClick: () => {
            actions.setSelectedNodeId(null)
            if (values.isCopyingNode) {
                actions.stopCopyingNode()
            }
        },
    })),

    subscriptions(({ actions }) => ({
        workflow: (hogFlow?: HogFlow) => {
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
            [urls.workflow(':id', ':tab')]: reactToTabChange,
        }
    }),
    events(({ actions, values }) => ({
        afterMount: () => {
            const handleKeyDown = (e: KeyboardEvent): void => {
                if (e.key === 'Escape' && values.isCopyingNode) {
                    actions.stopCopyingNode()
                }
            }

            document.addEventListener('keydown', handleKeyDown)

            // Store the handler so we can clean it up
            ;(actions as any)._keydownHandler = handleKeyDown
        },
        beforeUnmount: () => {
            const handler = (actions as any)._keydownHandler
            if (handler) {
                document.removeEventListener('keydown', handler)
            }
        },
    })),
])
