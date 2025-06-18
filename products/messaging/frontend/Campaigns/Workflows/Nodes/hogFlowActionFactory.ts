import { Edge, Handle, Node, Position, XYPosition } from '@xyflow/react'
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
import type { HogFlowAction, HogFlowEdge } from '../types'

type NodeHandle = Omit<Optional<Handle, 'width' | 'height'>, 'nodeId'> & { label?: string }

export interface HogFlowActionBuilder<T extends HogFlowAction = HogFlowAction> {
    setId(id: string): this
    setName(name: string): this
    setDescription(description: string): this
    setOnError(onError: 'continue' | 'abort' | 'complete' | 'branch'): this
    setPosition(position: XYPosition): this
    setCreatedAt(timestamp: number): this
    setUpdatedAt(timestamp: number): this
    build(): Node<T>
}

abstract class BaseHogFlowActionBuilder<T extends HogFlowAction> implements HogFlowActionBuilder<T> {
    protected id: string
    protected name: string = ''
    protected description: string = ''
    protected onError: 'continue' | 'abort' | 'complete' | 'branch' = 'continue'
    protected position: XYPosition = { x: 0, y: 0 }
    protected createdAt: number = Date.now()
    protected updatedAt: number = Date.now()

    constructor(id: string) {
        this.id = id
    }

    setId(id: string): this {
        this.id = id
        return this
    }

    setName(name: string): this {
        this.name = name
        return this
    }

    setDescription(description: string): this {
        this.description = description
        return this
    }

    setOnError(onError: 'continue' | 'abort' | 'complete' | 'branch'): this {
        this.onError = onError
        return this
    }

    setPosition(position: XYPosition): this {
        this.position = position
        return this
    }

    setCreatedAt(timestamp: number): this {
        this.createdAt = timestamp
        return this
    }

    setUpdatedAt(timestamp: number): this {
        this.updatedAt = timestamp
        return this
    }

    protected abstract getActionType(): T['type']
    protected abstract getConfig(): T extends { config: any } ? T['config'] : Record<string, never>
    public abstract getHandles(): NodeHandle[]
    protected abstract isEntryOrExit(): boolean

    build(): Node<T> {
        const actionData = {
            id: this.id,
            name: this.name,
            description: this.description,
            type: this.getActionType(),
            on_error: this.onError,
            created_at: this.createdAt,
            updated_at: this.updatedAt,
        } as any

        // Add config if it exists
        if ('config' in actionData) {
            actionData.config = this.getConfig()
        }

        return {
            id: this.id,
            type: this.getActionType(),
            data: actionData,
            handles: this.getHandles(),
            position: this.position,
            ...getDefaultNodeOptions(this.isEntryOrExit()),
        }
    }
}

// Trigger action builder
export class TriggerActionBuilder extends BaseHogFlowActionBuilder<Extract<HogFlowAction, { type: 'trigger' }>> {
    protected getActionType(): 'trigger' {
        return 'trigger'
    }

    protected getConfig(): Record<string, never> {
        return {} // Triggers don't have config
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `${this.id}_source`,
                type: 'source',
                position: Position.Bottom,
                ...BOTTOM_HANDLE_POSITION,
            },
        ]
    }

    protected isEntryOrExit(): boolean {
        return true
    }
}

// Exit action builder
export class ExitActionBuilder extends BaseHogFlowActionBuilder<Extract<HogFlowAction, { type: 'exit' }>> {
    private reason: string = 'Default exit'

    setReason(reason: string): this {
        this.reason = reason
        return this
    }

    protected getActionType(): 'exit' {
        return 'exit'
    }

    protected getConfig(): { reason: string } {
        return {
            reason: this.reason,
        }
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `${this.id}_target`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
        ]
    }

    protected isEntryOrExit(): boolean {
        return true
    }
}

// Message action builder
export class MessageActionBuilder extends BaseHogFlowActionBuilder<Extract<HogFlowAction, { type: 'message' }>> {
    private messageValue: any = NEW_TEMPLATE
    private channel = 'email' as const

    setMessageValue(value: any): this {
        this.messageValue = value
        return this
    }

    setChannel(channel: 'email'): this {
        this.channel = channel
        return this
    }

    protected getActionType(): 'message' {
        return 'message'
    }

    protected getConfig(): { message: { value: any }; channel: 'email' } {
        return {
            message: {
                value: this.messageValue,
            },
            channel: this.channel,
        }
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `${this.id}_target`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
            {
                id: `${this.id}_on_success`,
                type: 'source',
                position: Position.Left,
                label: 'Successful delivery',
                ...LEFT_HANDLE_POSITION,
            },
            {
                id: `${this.id}_on_error`,
                type: 'source',
                position: Position.Right,
                label: 'Delivery failed',
                ...RIGHT_HANDLE_POSITION,
            },
        ]
    }

    protected isEntryOrExit(): boolean {
        return false
    }
}

// Delay action builder
export class DelayActionBuilder extends BaseHogFlowActionBuilder<Extract<HogFlowAction, { type: 'delay' }>> {
    private delaySeconds: number = 15

    setDelaySeconds(seconds: number): this {
        this.delaySeconds = seconds
        return this
    }

    protected getActionType(): 'delay' {
        return 'delay'
    }

    protected getConfig(): { delay_seconds: number } {
        return {
            delay_seconds: this.delaySeconds,
        }
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `${this.id}_target`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
            {
                id: `${this.id}_source`,
                type: 'source',
                position: Position.Bottom,
                ...BOTTOM_HANDLE_POSITION,
            },
        ]
    }

    protected isEntryOrExit(): boolean {
        return false
    }
}

// Wait for condition action builder
export class WaitForConditionActionBuilder extends BaseHogFlowActionBuilder<
    Extract<HogFlowAction, { type: 'wait_for_condition' }>
> {
    private condition: any = null
    private timeoutSeconds: number = 300

    setCondition(condition: any): this {
        this.condition = condition
        return this
    }

    setTimeoutSeconds(seconds: number): this {
        this.timeoutSeconds = seconds
        return this
    }

    protected getActionType(): 'wait_for_condition' {
        return 'wait_for_condition'
    }

    protected getConfig(): { condition: any; timeout_seconds: number } {
        return {
            condition: this.condition,
            timeout_seconds: this.timeoutSeconds,
        }
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `${this.id}_target`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
            {
                id: `${this.id}_on_success`,
                type: 'source',
                position: Position.Left,
                label: 'Match',
                ...LEFT_HANDLE_POSITION,
            },
            {
                id: `${this.id}_on_error`,
                type: 'source',
                position: Position.Right,
                label: 'Max checks reached',
                ...RIGHT_HANDLE_POSITION,
            },
        ]
    }

    protected isEntryOrExit(): boolean {
        return false
    }
}

// Conditional branch action builder
export class ConditionalBranchActionBuilder extends BaseHogFlowActionBuilder<
    Extract<HogFlowAction, { type: 'conditional_branch' }>
> {
    private conditions: Array<{ filter: any; on_match: string }> = []
    private waitDurationSeconds?: number

    setConditions(conditions: Array<{ filter: any; on_match: string }>): this {
        this.conditions = conditions
        return this
    }

    setWaitDurationSeconds(seconds?: number): this {
        this.waitDurationSeconds = seconds
        return this
    }

    protected getActionType(): 'conditional_branch' {
        return 'conditional_branch'
    }

    protected getConfig(): { conditions: Array<{ filter: any; on_match: string }>; wait_duration_seconds?: number } {
        return {
            conditions: this.conditions,
            wait_duration_seconds: this.waitDurationSeconds,
        }
    }

    public getHandles(): NodeHandle[] {
        return [
            {
                id: `${this.id}_target`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
            {
                id: `${this.id}_on_match_condition_0`,
                type: 'source',
                position: Position.Left,
                label: 'Match condition 1',
                ...LEFT_HANDLE_POSITION,
            },
            {
                id: `${this.id}_on_error`,
                type: 'source',
                position: Position.Right,
                label: 'No match',
                ...RIGHT_HANDLE_POSITION,
            },
        ]
    }

    protected isEntryOrExit(): boolean {
        return false
    }
}

// Factory class for creating action builders
export class HogFlowActionFactory {
    static createTrigger(id: string): TriggerActionBuilder {
        return new TriggerActionBuilder(id)
    }

    static createExit(id: string): ExitActionBuilder {
        return new ExitActionBuilder(id)
    }

    static createMessage(id: string): MessageActionBuilder {
        return new MessageActionBuilder(id)
    }

    static createDelay(id: string): DelayActionBuilder {
        return new DelayActionBuilder(id)
    }

    static createWaitForCondition(id: string): WaitForConditionActionBuilder {
        return new WaitForConditionActionBuilder(id)
    }

    static createConditionalBranch(id: string): ConditionalBranchActionBuilder {
        return new ConditionalBranchActionBuilder(id)
    }

    // Factory method for creating nodes from toolbar nodes (replaces createNewNode)
    static createFromToolbarNode(
        toolbarNode: ToolbarNode,
        nodeId?: string,
        position?: XYPosition
    ): Node<HogFlowAction> {
        const id = nodeId || `${toolbarNode.type}_${Date.now()}`

        switch (toolbarNode.type) {
            case 'message':
                return this.createMessage(id)
                    .setPosition(position || { x: 0, y: 0 })
                    .build()
            case 'delay':
                return this.createDelay(id)
                    .setPosition(position || { x: 0, y: 0 })
                    .build()
            case 'wait_for_condition':
                return this.createWaitForCondition(id)
                    .setPosition(position || { x: 0, y: 0 })
                    .build()
            case 'conditional_branch':
                return this.createConditionalBranch(id)
                    .setPosition(position || { x: 0, y: 0 })
                    .build()
            default:
                throw new Error(`Unsupported node type: ${(toolbarNode as any).type}`)
        }
    }

    // Factory method for creating default nodes
    static createDefaultNodes(): Node<HogFlowAction>[] {
        return [
            this.createTrigger('trigger_node').setName('Trigger').setPosition({ x: 0, y: 0 }).build(),
            this.createExit('exit_node').setName('Exit').setPosition({ x: 0, y: 100 }).build(),
        ]
    }

    // Factory method for creating default edges
    static createDefaultEdges(): Edge<HogFlowEdge>[] {
        return [
            {
                id: 'trigger_node->exit_node',
                source: 'trigger_node',
                sourceHandle: 'trigger_node_source',
                target: 'exit_node',
                targetHandle: 'exit_node_target',
                ...getDefaultEdgeOptions(),
            },
        ]
    }

    // Utility method for creating edges for a new node
    static createEdgesForNewNode(
        nodeId: string,
        nodeType: HogFlowAction['type'],
        edgeToInsertNodeInto: Edge<HogFlowEdge>
    ): Edge<HogFlowEdge>[] {
        const builder = this.createBuilderForType(nodeType, nodeId)
        const handles = builder.getHandles()

        return handles.map((handle) => {
            // This is an incoming edge
            if (handle.type === 'target') {
                return {
                    id: `${edgeToInsertNodeInto.source}->${nodeId}${handle.id ? `:${handle.id}` : ''}`,
                    source: edgeToInsertNodeInto.source,
                    target: nodeId,
                    sourceHandle: edgeToInsertNodeInto.sourceHandle,
                    targetHandle: handle.id,
                    ...getDefaultEdgeOptions(),
                    label: edgeToInsertNodeInto?.label,
                }
            }
            // This is an outgoing edge
            return {
                id: `${nodeId}->${edgeToInsertNodeInto.target}${handle.id ? `:${handle.id}` : ''}`,
                source: nodeId,
                target: edgeToInsertNodeInto.target,
                sourceHandle: handle.id,
                targetHandle: edgeToInsertNodeInto.targetHandle,
                ...getDefaultEdgeOptions(),
                label: handle.label,
            }
        })
    }

    private static createBuilderForType(type: HogFlowAction['type'], id: string): BaseHogFlowActionBuilder<any> {
        switch (type) {
            case 'trigger':
                return this.createTrigger(id)
            case 'exit':
                return this.createExit(id)
            case 'message':
                return this.createMessage(id)
            case 'delay':
                return this.createDelay(id)
            case 'wait_for_condition':
                return this.createWaitForCondition(id)
            case 'conditional_branch':
                return this.createConditionalBranch(id)
            default:
                throw new Error(`Unsupported node type: ${type}`)
        }
    }
}

// Utility functions for backward compatibility
export const getNodeInputs = (node: HogFlowAction | ToolbarNode): Record<string, CyclotronJobInputType> => {
    switch (node.type) {
        case 'message':
            return {
                name: { value: ('config' in node && node.name) || '' },
                email: { value: ('config' in node && node.config.message.value) || NEW_TEMPLATE },
            }
        case 'delay':
            return {
                name: { value: ('config' in node && node.name) || '' },
                duration: { value: ('config' in node && node.config.delay_seconds) || 15 },
            }
        case 'wait_for_condition':
            return {
                name: { value: ('config' in node && node.name) || '' },
            }
        case 'conditional_branch':
            return {
                name: { value: ('config' in node && node.name) || '' },
            }
        default:
            return {}
    }
}

export const getNodeInputsSchema = (node: HogFlowAction | ToolbarNode): CyclotronJobInputSchemaType[] => {
    switch (node.type) {
        case 'message':
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
        case 'delay':
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
                    label: 'Duration (minutes)',
                    required: true,
                },
            ]
        case 'wait_for_condition':
            return []
        case 'conditional_branch':
            return [
                {
                    type: 'string',
                    key: 'name',
                    label: 'Name',
                    required: false,
                },
            ]
        default:
            return []
    }
}
