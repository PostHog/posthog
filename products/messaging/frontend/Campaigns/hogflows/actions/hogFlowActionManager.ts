import { Edge, getSmoothStepPath, Handle, Node, Position } from '@xyflow/react'
import { uuid } from 'lib/utils'
import { NEW_TEMPLATE } from 'products/messaging/frontend/TemplateLibrary/constants'

import { CyclotronJobInputSchemaType, CyclotronJobInputType, Optional } from '~/types'

import {
    BOTTOM_HANDLE_POSITION,
    getDefaultEdgeOptions,
    getDefaultNodeOptions,
    LEFT_HANDLE_POSITION,
    NODE_HEIGHT,
    NODE_WIDTH,
    RIGHT_HANDLE_POSITION,
    TOP_HANDLE_POSITION,
} from '../constants'
import { ToolbarNode } from '../Toolbar'
import type { HogFlow, HogFlowAction } from '../types'

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
            case 'wait_until_condition':
                return new WaitUntilConditionAction(action)
            case 'conditional_branch':
                return new ConditionalBranchAction(action)
            case 'exit':
                return new ExitAction(action)
            case 'function': {
                // TODO: Implement HogFunctionAction
                throw new Error('HogFunctionAction not implemented yet')
            }
            default: {
                throw new Error(`Unsupported action type: ${action.type}`)
            }
        }
    },

    fromToolbarNode(toolbarNode: ToolbarNode, edgeToInsertNodeInto: Edge): BaseNode<HogFlowAction['type']> {
        switch (toolbarNode.type) {
            case 'message':
                return MessageAction.fromToolbarNode(toolbarNode, edgeToInsertNodeInto)
            case 'delay':
                return DelayAction.fromToolbarNode(toolbarNode, edgeToInsertNodeInto)
            case 'wait_until_condition':
                return WaitUntilConditionAction.fromToolbarNode(toolbarNode, edgeToInsertNodeInto)
            case 'conditional_branch':
                return ConditionalBranchAction.fromToolbarNode(toolbarNode, edgeToInsertNodeInto)
        }
    },

    insertNodeIntoDropzone(
        actions: HogFlowAction[],
        toolbarNode: ToolbarNode,
        dropzone: Node<{ edge: Edge }>
    ): HogFlowAction[] {
        const edgeToInsertNodeInto = dropzone?.data.edge

        const newNode = this.fromToolbarNode(toolbarNode, edgeToInsertNodeInto)
        const edgeSourceNode = actions.find((action) => action.id === edgeToInsertNodeInto.source)

        if (!edgeSourceNode) {
            throw new Error('Edge source node not found')
        }

        Object.keys(edgeSourceNode.next_actions).forEach((key) => {
            edgeSourceNode.next_actions[key] = newNode.action.id
        })

        return [...actions.slice(0, -1), newNode.action, actions[actions.length - 1]]
    },

    // When a new node is starting to be dragged into the workflow, show a dropzone node in the middle of every edge
    addDropzoneNodes(nodes: Node<HogFlowAction>[], edges: Edge[]): Node<HogFlowAction>[] {
        const newNodes: Node[] = [...nodes]

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

                newNodes.push({
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

        return newNodes as Node<HogFlowAction>[]
    },

    getNodesFromHogFlow(hogFlow: HogFlow): Node<HogFlowAction>[] {
        return hogFlow.actions
            .map((action: HogFlowAction) => HogFlowActionManager.fromAction(action))
            .map((hogFlowAction: BaseNode<HogFlowAction['type']>) => {
                return {
                    id: hogFlowAction.action.id,
                    type: hogFlowAction.action.type,
                    data: hogFlowAction.action,
                    position: { x: 0, y: 0 },
                    handles: hogFlowAction.getHandles(),
                    ...getDefaultNodeOptions(['trigger', 'exit'].includes(hogFlowAction.action.type)),
                }
            })
    },

    getEdgesFromHogFlow(hogFlow: HogFlow): Edge[] {
        return hogFlow.actions.flatMap((action: HogFlowAction) =>
            Object.entries(action.next_actions).map(([branch, next_action_id]) => ({
                id: `${branch}_${action.id}->${next_action_id}`,
                source: action.id,
                sourceHandle: `${branch}_${action.id}`,
                target: next_action_id,
                targetHandle: `target_${next_action_id}`,
                ...getDefaultEdgeOptions(),
            }))
        )
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

    abstract getHandles(): NodeHandle[]
    abstract getInputs(): Record<string, CyclotronJobInputType>
    abstract getInputsSchema(): CyclotronJobInputSchemaType[]
    abstract setInput(key: string, value: any): void
}

class TriggerAction extends BaseNode<'trigger'> {
    public getHandles(): NodeHandle[] {
        return [
            {
                id: `continue_${this.action.id}`,
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
                id: `target_${this.action.id}`,
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
    public static fromToolbarNode(toolbarNode: ToolbarNode, edgeToInsertNodeInto: Edge): MessageAction {
        const id = HogFlowActionManager.generateActionId(toolbarNode.type)
        return new MessageAction({
            id,
            name: 'Message',
            description: '',
            type: 'message',
            config: { message: { value: NEW_TEMPLATE }, channel: 'email' },
            on_error: 'continue',
            created_at: Date.now(),
            updated_at: Date.now(),
            next_actions: {
                continue: edgeToInsertNodeInto.target,
            },
        })
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `target_${this.action.id}`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
            {
                id: `continue_${this.action.id}`,
                type: 'source',
                position: Position.Bottom,
                label: 'Successful delivery',
                ...BOTTOM_HANDLE_POSITION,
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
    public static fromToolbarNode(toolbarNode: ToolbarNode, edgeToInsertNodeInto: Edge): DelayAction {
        const id = HogFlowActionManager.generateActionId(toolbarNode.type)
        return new DelayAction({
            id,
            name: 'Delay',
            description: '',
            type: 'delay',
            config: { delay_duration: '15s' },
            on_error: 'continue',
            created_at: Date.now(),
            updated_at: Date.now(),
            next_actions: {
                continue: edgeToInsertNodeInto.target,
            },
        })
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `target_${this.action.id}`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
            {
                id: `continue_${this.action.id}`,
                type: 'source',
                position: Position.Bottom,
                ...BOTTOM_HANDLE_POSITION,
            },
        ]
    }

    getInputs(): Record<string, CyclotronJobInputType> {
        return {
            name: { value: this.action.name || '' },
            duration: { value: this.action.config?.delay_duration || '1h' },
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
                this.action.config.delay_duration = value
                break
        }
    }
}

class WaitUntilConditionAction extends BaseNode<'wait_until_condition'> {
    public static fromToolbarNode(toolbarNode: ToolbarNode, edgeToInsertNodeInto: Edge): WaitUntilConditionAction {
        const id = HogFlowActionManager.generateActionId(toolbarNode.type)
        return new WaitUntilConditionAction({
            id,
            name: 'Wait until...',
            description: '',
            type: 'wait_until_condition',
            config: { condition: { filter: null }, max_wait_duration: '300s' },
            on_error: 'continue',
            created_at: Date.now(),
            updated_at: Date.now(),
            next_actions: {
                continue: edgeToInsertNodeInto.target,
            },
        })
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `target_${this.action.id}`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
            {
                id: `continue_${this.action.id}`,
                type: 'source',
                position: Position.Left,
                label: 'Match',
                ...LEFT_HANDLE_POSITION,
            },
            {
                id: `abort_${this.action.id}`,
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
    public static fromToolbarNode(toolbarNode: ToolbarNode, edgeToInsertNodeInto: Edge): ConditionalBranchAction {
        const id = HogFlowActionManager.generateActionId(toolbarNode.type)
        return new ConditionalBranchAction({
            id,
            name: 'Conditional',
            description: '',
            type: 'conditional_branch',
            config: { conditions: [] },
            on_error: 'continue',
            created_at: Date.now(),
            updated_at: Date.now(),
            next_actions: {
                condition_0: edgeToInsertNodeInto.target,
                continue: edgeToInsertNodeInto.target,
            },
        })
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `target_${this.action.id}`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
            {
                id: `condition_0_${this.action.id}`,
                type: 'source',
                position: Position.Left,
                label: 'Match condition 1',
                ...LEFT_HANDLE_POSITION,
            },
            {
                id: `continue_${this.action.id}`,
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
