import { Edge, Handle, Node, Position } from '@xyflow/react'
import { uuid } from 'lib/utils'
import { NEW_TEMPLATE } from 'products/messaging/frontend/TemplateLibrary/constants'

import { Optional } from '~/types'

import {
    BOTTOM_HANDLE_POSITION,
    getDefaultNodeOptions,
    LEFT_HANDLE_POSITION,
    RIGHT_HANDLE_POSITION,
    TOP_HANDLE_POSITION,
} from '../constants'
import { ToolbarNode } from '../HogFlowEditorToolbar'
import type { HogFlowAction } from '../types'

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

    fromReactFlowNode(node: Node<HogFlowAction>): BaseHogFlowActionNode<HogFlowAction['type']> {
        return this.fromAction(node.data)
    },

    fromAction(action: HogFlowAction): BaseHogFlowActionNode<HogFlowAction['type']> {
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

    fromToolbarNode(
        toolbarNode: ToolbarNode,
        edgeToInsertNodeInto: Edge
    ): BaseHogFlowActionNode<HogFlowAction['type']> {
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
}

export abstract class BaseHogFlowActionNode<T extends HogFlowAction['type']> {
    action: Extract<HogFlowAction, { type: T }>

    constructor(action: Extract<HogFlowAction, { type: T }>) {
        this.action = action

        if (!this.action.config) {
            this.action.config = this.getDefaultConfig()
        }
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

    abstract getDefaultConfig(): Extract<HogFlowAction, { type: T }>['config']
    abstract getHandles(): NodeHandle[]

    updateConfig(config: Extract<HogFlowAction, { type: T }>['config']): void {
        this.action.config = config
    }

    partialUpdateConfig(config: Partial<Extract<HogFlowAction, { type: T }>['config']>): void {
        console.log('partialUpdateConfig', config)
        this.action.config = { ...this.action.config, ...config }
    }
}

export class TriggerAction extends BaseHogFlowActionNode<'trigger'> {
    public getDefaultConfig(): Extract<HogFlowAction, { type: 'trigger' }>['config'] {
        return {
            type: 'event',
            filters: {},
        }
    }

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
}

class ExitAction extends BaseHogFlowActionNode<'exit'> {
    public getDefaultConfig(): Extract<HogFlowAction, { type: 'exit' }>['config'] {
        return {
            reason: 'Default exit',
        }
    }

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
}

class MessageAction extends BaseHogFlowActionNode<'message'> {
    public getDefaultConfig(): Extract<HogFlowAction, { type: 'message' }>['config'] {
        return {
            message: { value: NEW_TEMPLATE },
            channel: 'email',
        }
    }

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
                continue: {
                    action_id: edgeToInsertNodeInto.target,
                },
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

    // getInputs(): Record<string, CyclotronJobInputType> {
    //     return {
    //         name: { value: this.action.name || '' },
    //         email: { value: this.action.config?.message?.value || NEW_TEMPLATE },
    //     }
    // }

    // getInputsSchema(): CyclotronJobInputSchemaType[] {
    //     return [
    //         {
    //             type: 'string',
    //             key: 'name',
    //             label: 'Name',
    //             required: false,
    //         },
    //         {
    //             type: 'email',
    //             key: 'email',
    //             label: 'Email',
    //             required: true,
    //         },
    //     ]
    // }

    // setInput(key: 'name' | 'email', value: any): void {
    //     switch (key) {
    //         case 'name':
    //             this.action.name = value
    //             break
    //         case 'email':
    //             this.action.config.message.value = value
    //             break
    //     }
    // }
}

class DelayAction extends BaseHogFlowActionNode<'delay'> {
    public getDefaultConfig(): Extract<HogFlowAction, { type: 'delay' }>['config'] {
        return {
            delay_duration: '10m',
        }
    }

    public static fromToolbarNode(toolbarNode: ToolbarNode, edgeToInsertNodeInto: Edge): DelayAction {
        const id = HogFlowActionManager.generateActionId(toolbarNode.type)
        return new DelayAction({
            id,
            name: 'Wait',
            description: '',
            type: 'delay',
            config: { delay_duration: '15s' },
            on_error: 'continue',
            created_at: Date.now(),
            updated_at: Date.now(),
            next_actions: {
                continue: {
                    action_id: edgeToInsertNodeInto.target,
                },
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

    // getInputs(): Record<string, CyclotronJobInputType> {
    //     return {
    //         name: { value: this.action.name || '' },
    //         duration: { value: this.action.config?.delay_duration || '1h' },
    //     }
    // }

    // getInputsSchema(): CyclotronJobInputSchemaType[] {
    //     return [
    //         {
    //             type: 'string',
    //             key: 'name',
    //             label: 'Name',
    //             required: false,
    //         },
    //         {
    //             type: 'string',
    //             key: 'duration',
    //             label: 'Duration',
    //             required: true,
    //         },
    //     ]
    // }

    // setInput(key: 'name' | 'duration', value: any): void {
    //     switch (key) {
    //         case 'name':
    //             this.action.name = value
    //             break
    //         case 'duration':
    //             this.action.config.delay_duration = value
    //             break
    //     }
    // }
}

class WaitUntilConditionAction extends BaseHogFlowActionNode<'wait_until_condition'> {
    public getDefaultConfig(): Extract<HogFlowAction, { type: 'wait_until_condition' }>['config'] {
        return {
            condition: { filter: null },
            max_wait_duration: '300s',
        }
    }

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
                continue: {
                    action_id: edgeToInsertNodeInto.target,
                },
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
                ...LEFT_HANDLE_POSITION,
            },
            {
                id: `abort_${this.action.id}`,
                type: 'source',
                position: Position.Right,
                ...RIGHT_HANDLE_POSITION,
            },
        ]
    }

    // getInputs(): Record<string, CyclotronJobInputType> {
    //     return {
    //         name: { value: this.action.name || '' },
    //     }
    // }

    // getInputsSchema(): CyclotronJobInputSchemaType[] {
    //     return []
    // }

    // setInput(key: 'name', value: any): void {
    //     switch (key) {
    //         case 'name':
    //             this.action.name = value
    //             break
    //     }
    // }
}

class ConditionalBranchAction extends BaseHogFlowActionNode<'conditional_branch'> {
    public getDefaultConfig(): Extract<HogFlowAction, { type: 'conditional_branch' }>['config'] {
        return {
            conditions: [],
        }
    }

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
                condition_0: {
                    action_id: edgeToInsertNodeInto.target,
                    label: 'Match condition 1',
                },
                continue: {
                    action_id: edgeToInsertNodeInto.target,
                    label: 'No match',
                },
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
                ...LEFT_HANDLE_POSITION,
            },
            {
                id: `continue_${this.action.id}`,
                type: 'source',
                position: Position.Right,
                ...RIGHT_HANDLE_POSITION,
            },
        ]
    }

    // getInputs(): Record<string, CyclotronJobInputType> {
    //     return {
    //         name: { value: this.action.name || '' },
    //     }
    // }

    // getInputsSchema(): CyclotronJobInputSchemaType[] {
    //     return [
    //         {
    //             type: 'string',
    //             key: 'name',
    //             label: 'Name',
    //             required: false,
    //         },
    //     ]
    // }

    // setInput(key: 'name', value: any): void {
    //     switch (key) {
    //         case 'name':
    //             this.action.name = value
    //             break
    //     }
    // }
}
