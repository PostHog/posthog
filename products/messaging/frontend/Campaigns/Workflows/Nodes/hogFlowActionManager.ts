import { Edge, getSmoothStepPath, Handle, Node, Position } from '@xyflow/react'
import { uuid } from 'lib/utils'
import { NEW_TEMPLATE } from 'products/messaging/frontend/TemplateLibrary/constants'

import { CyclotronJobInputSchemaType, CyclotronJobInputType, Optional } from '~/types'

import {
    BOTTOM_HANDLE_POSITION,
    getDefaultEdgeOptions,
    getDefaultNodeOptions,
    LEFT_HANDLE_POSITION,
    RIGHT_HANDLE_POSITION,
    TOP_HANDLE_POSITION,
} from '../constants'
import { ToolbarNode } from '../Toolbar'
import type { HogFlow, HogFlowAction, HogFlowEdge } from '../types'

type NodeHandle = Omit<Optional<Handle, 'width' | 'height'>, 'nodeId'> & { label?: string }

/**
 * HogFlowActionManager - your one-stop shop for dealing with HogFlow<->ReactFlow conversions
 *
 * Manages the translation between HogFlowActions and Nodes, the action's inputs / inputs schemas,
 * and provides some convenience methods for setting up nodes and edges.
 *
 */
export const HogFlowActionManager = {
    generateActionId(type: HogFlowAction['type']): string {
        return `action_${type}_${uuid()}`
    },

    fromReactFlowNode(node: Node<HogFlowAction>): BaseNode<HogFlowAction['type']> {
        return this.fromAction(node.data)
    },

    fromAction(action: HogFlowAction): BaseNode<HogFlowAction['type']> {
        switch (action.type) {
            case 'trigger':
                return new TriggerAction(action)
            case 'message':
                return new MessageAction(action)
            case 'delay':
                return new DelayAction(action)
            case 'wait_for_condition':
                return new WaitForConditionAction(action)
            case 'conditional_branch':
                return new ConditionalBranchAction(action)
            case 'exit':
                return new ExitAction(action)
            case 'hog_function': {
                // TODO: Implement HogFunctionAction
                throw new Error('HogFunctionAction not implemented yet')
            }
            default: {
                throw new Error(`Unsupported action type: ${action}`)
            }
        }
    },

    fromToolbarNode(toolbarNode: ToolbarNode): BaseNode<HogFlowAction['type']> {
        switch (toolbarNode.type) {
            case 'message':
                return MessageAction.fromToolbarNode(toolbarNode)
            case 'delay':
                return DelayAction.fromToolbarNode(toolbarNode)
            case 'wait_for_condition':
                return WaitForConditionAction.fromToolbarNode(toolbarNode)
            case 'conditional_branch':
                return ConditionalBranchAction.fromToolbarNode(toolbarNode)
            default:
                throw new Error(`Unsupported node type: ${(toolbarNode as any).type}`)
        }
    },

    createDefaultHogflowNodesAndEdges(): { nodes: Node<HogFlowAction>[]; edges: Edge<HogFlowEdge>[] } {
        const triggerNodeId = this.generateActionId('trigger')
        const exitNodeId = this.generateActionId('exit')
        const nodes = [
            new TriggerAction({
                id: triggerNodeId,
                name: 'Trigger',
                description: '',
                type: 'trigger',
                on_error: 'continue',
                created_at: Date.now(),
                updated_at: Date.now(),
            }).toReactFlowNode(),
            new ExitAction({
                id: exitNodeId,
                name: 'Exit',
                description: '',
                type: 'exit',
                config: { reason: 'Default exit' },
                on_error: 'continue',
                created_at: Date.now(),
                updated_at: Date.now(),
            }).toReactFlowNode(),
        ]

        const edges = [
            {
                id: `${triggerNodeId}->${exitNodeId}`,
                source: triggerNodeId,
                sourceHandle: `${triggerNodeId}_source`,
                target: exitNodeId,
                targetHandle: `${exitNodeId}_target`,
                ...getDefaultEdgeOptions(),
            },
        ]

        return { nodes, edges }
    },

    createNodeAndEdgesFromToolbarNode(
        toolbarNode: ToolbarNode,
        edgeToInsertNodeInto: Edge<HogFlowEdge>
    ): { node: Node<HogFlowAction>; edges: Edge<HogFlowEdge>[] } {
        const node = this.fromToolbarNode(toolbarNode)
        const edges = node.createEdgesForNewNode(edgeToInsertNodeInto)

        return { node: node.toReactFlowNode(), edges }
    },

    // When a new node is starting to be dragged into the workflow, show a dropzone node in the middle of every edge
    addDropzoneNodes(nodes: Node<HogFlowAction>[], edges: Edge<HogFlowEdge>[]): Node<HogFlowAction>[] {
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
                    position: { x: labelX, y: labelY },
                    data: {
                        id: dropzoneId,
                        name: '',
                        description: '',
                        // Hack: any cast because these are temporary nodes that are never persisted.
                        type: 'dropzone' as any,
                        config: {} as any,
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
    },

    getNodesFromHogFlow(hogFlow: HogFlow): Node<HogFlowAction>[] {
        return hogFlow.actions.map((action: HogFlowAction) => {
            return {
                id: action.id,
                type: action.type,
                data: action,
                position: { x: 0, y: 0 },
                ...getDefaultNodeOptions(['trigger', 'exit'].includes(action.type)),
            }
        })
    },

    getEdgesFromHogFlow(hogFlow: HogFlow): Edge<HogFlowEdge>[] {
        return hogFlow.edges.map((edge: any) => ({
            id: `${edge.from}->${edge.to}`,
            source: edge.from,
            target: edge.to,
            sourceHandle: edge.sourceHandle,
            targetHandle: edge.targetHandle,
            ...getDefaultEdgeOptions(),
        }))
    },
}

abstract class BaseNode<T extends HogFlowAction['type']> {
    action: Extract<HogFlowAction, { type: T }>

    constructor(action: Extract<HogFlowAction, { type: T }>) {
        this.action = action
    }

    toReactFlowNode(): Node<HogFlowAction> {
        return {
            id: this.action.id,
            type: this.action.type,
            data: this.action,
            position: { x: 0, y: 0 },
            handles: this.getHandles(),
            ...getDefaultNodeOptions(['trigger', 'exit'].includes(this.action.type)),
        }
    }

    createEdgesForNewNode(edgeToInsertNodeInto: Edge<HogFlowEdge>): Edge<HogFlowEdge>[] {
        const handles = this.getHandles()

        return handles.map((handle) => {
            if (handle.type === 'target') {
                return {
                    id: `${edgeToInsertNodeInto.source}->${this.action.id}${handle.id ? `:${handle.id}` : ''}`,
                    source: edgeToInsertNodeInto.source,
                    target: this.action.id,
                    sourceHandle: edgeToInsertNodeInto.sourceHandle,
                    targetHandle: handle.id,
                    ...getDefaultEdgeOptions(),
                    label: edgeToInsertNodeInto?.label,
                }
            }
            return {
                id: `${this.action.id}->${edgeToInsertNodeInto.target}${handle.id ? `:${handle.id}` : ''}`,
                source: this.action.id,
                target: edgeToInsertNodeInto.target,
                sourceHandle: handle.id,
                targetHandle: edgeToInsertNodeInto.targetHandle,
                ...getDefaultEdgeOptions(),
                label: handle.label,
            }
        })
    }

    abstract getHandles(): NodeHandle[]
    abstract getInputs(): Record<string, CyclotronJobInputType>
    abstract getInputsSchema(): CyclotronJobInputSchemaType[]
    abstract setInput(key: string, value: any): void
}

class TriggerAction extends BaseNode<'trigger'> {
    public getHandles(): NodeHandle[] {
        return [
            {
                id: `${this.action.id}_source`,
                type: 'source',
                position: Position.Bottom,
                ...BOTTOM_HANDLE_POSITION,
            },
        ]
    }

    getInputs(): Record<string, CyclotronJobInputType> {
        return {}
    }

    getInputsSchema(): CyclotronJobInputSchemaType[] {
        return []
    }

    setInput(): void {
        throw new Error('TriggerAction does not have inputs')
    }
}

class ExitAction extends BaseNode<'exit'> {
    public getHandles(): NodeHandle[] {
        return [
            {
                id: `${this.action.id}_target`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
        ]
    }

    getInputs(): Record<string, CyclotronJobInputType> {
        return {
            reason: { value: this.action.config?.reason || 'Default exit' },
        }
    }

    getInputsSchema(): CyclotronJobInputSchemaType[] {
        return [
            {
                key: 'reason',
                label: 'Exit reason',
                type: 'string',
                required: false,
                description: 'The reason for exiting the workflow',
                default: 'Default exit',
                secret: false,
            },
        ]
    }

    setInput(key: 'reason', value: any): void {
        switch (key) {
            case 'reason':
                this.action.config.reason = value
                break
        }
    }
}

class MessageAction extends BaseNode<'message'> {
    public static fromToolbarNode(toolbarNode: ToolbarNode): MessageAction {
        const id = HogFlowActionManager.generateActionId(toolbarNode.type)
        return new MessageAction({
            id,
            name: '',
            description: '',
            type: 'message',
            config: { message: { value: NEW_TEMPLATE }, channel: 'email' },
            on_error: 'continue',
            created_at: Date.now(),
            updated_at: Date.now(),
        })
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `${this.action.id}_target`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
            {
                id: `${this.action.id}_on_success`,
                type: 'source',
                position: Position.Left,
                label: 'Successful delivery',
                ...LEFT_HANDLE_POSITION,
            },
            {
                id: `${this.action.id}_on_error`,
                type: 'source',
                position: Position.Right,
                label: 'Delivery failed',
                ...RIGHT_HANDLE_POSITION,
            },
        ]
    }

    getInputs(): Record<string, CyclotronJobInputType> {
        return {
            name: { value: this.action.name || '' },
            email: { value: this.action.config?.message?.value || NEW_TEMPLATE },
        }
    }

    getInputsSchema(): CyclotronJobInputSchemaType[] {
        return [
            {
                type: 'string',
                key: 'name',
                label: 'Name',
                required: false,
            },
            {
                type: 'email',
                key: 'email',
                label: 'Email',
                required: true,
            },
        ]
    }

    setInput(key: 'name' | 'email', value: any): void {
        switch (key) {
            case 'name':
                this.action.name = value
                break
            case 'email':
                this.action.config.message.value = value
                break
        }
    }
}

class DelayAction extends BaseNode<'delay'> {
    public static fromToolbarNode(toolbarNode: ToolbarNode): DelayAction {
        const id = HogFlowActionManager.generateActionId(toolbarNode.type)
        return new DelayAction({
            id,
            name: '',
            description: '',
            type: 'delay',
            config: { delay_seconds: 15 },
            on_error: 'continue',
            created_at: Date.now(),
            updated_at: Date.now(),
        })
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `${this.action.id}_target`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
            {
                id: `${this.action.id}_source`,
                type: 'source',
                position: Position.Bottom,
                ...BOTTOM_HANDLE_POSITION,
            },
        ]
    }

    getInputs(): Record<string, CyclotronJobInputType> {
        return {
            name: { value: this.action.name || '' },
            duration: { value: this.action.config?.delay_seconds || '1h' },
        }
    }

    getInputsSchema(): CyclotronJobInputSchemaType[] {
        return [
            {
                type: 'string',
                key: 'name',
                label: 'Name',
                required: false,
            },
            {
                type: 'string',
                key: 'duration',
                label: 'Duration',
                required: true,
            },
        ]
    }

    setInput(key: 'name' | 'duration', value: any): void {
        switch (key) {
            case 'name':
                this.action.name = value
                break
            case 'duration':
                this.action.config.delay_seconds = value
                break
        }
    }
}

class WaitForConditionAction extends BaseNode<'wait_for_condition'> {
    public static fromToolbarNode(toolbarNode: ToolbarNode): WaitForConditionAction {
        const id = HogFlowActionManager.generateActionId(toolbarNode.type)
        return new WaitForConditionAction({
            id,
            name: '',
            description: '',
            type: 'wait_for_condition',
            config: { condition: null, timeout_seconds: 300 },
            on_error: 'continue',
            created_at: Date.now(),
            updated_at: Date.now(),
        })
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `${this.action.id}_target`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
            {
                id: `${this.action.id}_on_success`,
                type: 'source',
                position: Position.Left,
                label: 'Match',
                ...LEFT_HANDLE_POSITION,
            },
            {
                id: `${this.action.id}_on_error`,
                type: 'source',
                position: Position.Right,
                label: 'Max checks reached',
                ...RIGHT_HANDLE_POSITION,
            },
        ]
    }

    getInputs(): Record<string, CyclotronJobInputType> {
        return {
            name: { value: this.action.name || '' },
        }
    }

    getInputsSchema(): CyclotronJobInputSchemaType[] {
        return []
    }

    setInput(key: 'name', value: any): void {
        switch (key) {
            case 'name':
                this.action.name = value
                break
        }
    }
}

class ConditionalBranchAction extends BaseNode<'conditional_branch'> {
    public static fromToolbarNode(toolbarNode: ToolbarNode): ConditionalBranchAction {
        const id = HogFlowActionManager.generateActionId(toolbarNode.type)
        return new ConditionalBranchAction({
            id,
            name: '',
            description: '',
            type: 'conditional_branch',
            config: { conditions: [] },
            on_error: 'continue',
            created_at: Date.now(),
            updated_at: Date.now(),
        })
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `${this.action.id}_target`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
            {
                id: `${this.action.id}_on_match_condition_0`,
                type: 'source',
                position: Position.Left,
                label: 'Match condition 1',
                ...LEFT_HANDLE_POSITION,
            },
            {
                id: `${this.action.id}_on_error`,
                type: 'source',
                position: Position.Right,
                label: 'No match',
                ...RIGHT_HANDLE_POSITION,
            },
        ]
    }

    getInputs(): Record<string, CyclotronJobInputType> {
        return {
            name: { value: this.action.name || '' },
        }
    }

    getInputsSchema(): CyclotronJobInputSchemaType[] {
        return [
            {
                type: 'string',
                key: 'name',
                label: 'Name',
                required: false,
            },
        ]
    }

    setInput(key: 'name', value: any): void {
        switch (key) {
            case 'name':
                this.action.name = value
                break
        }
    }
}
