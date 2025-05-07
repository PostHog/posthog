import { Edge, Node, ReactFlowJsonObject } from '@xyflow/react'

import { EventPropertyFilter, PersonPropertyFilter, UserBasicType } from '~/types'

///////////////////////////////////////////////////////////////////////////////
// Workflow - sync with plugin-server/src/types.ts
///////////////////////////////////////////////////////////////////////////////
export interface Workflow {
    id: string
    name: string
    description: string
    json: ReactFlowJsonObject<WorkflowNode, WorkflowEdge>
    created_at: string | null
    updated_at: string | null
    created_by: UserBasicType | null
}

///////////////////////////////////////////////////////////////////////////////
// Nodes - sync with plugin-server/src/types.ts
///////////////////////////////////////////////////////////////////////////////
export type WorkflowNode = Node<WorkflowNodeData, WorkflowNodeType>
export type WorkflowNodeType = 'trigger' | 'message' | 'condition' | 'delay' | 'exit'
export interface WorkflowNodeData extends Record<string, unknown> {
    name: string
    description: string
    config: WorkflowNodeConfig
}
export type WorkflowNodeConfig = TriggerNodeConfig | MessageNodeConfig | ConditionNodeConfig | DelayNodeConfig

export type TriggerNodeConfig = {
    filters: WorkflowFilters
}

export type MessageNodeConfig = {
    type: 'email'
    content: {
        email: {
            from: string
            html: string
            text: string
            design: Record<string, unknown>
            subject: string
        }
    }
}

/**
 * Each condition is a set of one or more filters that can be matched against the event or latest person properties.
 * Conditions are connected to the next node by a condition_match edge type. condition_match edges are 1:1 with conditions.
 */
export type ConditionNodeConfig = {
    conditions: WorkflowFilters
}

export type DelayNodeConfig = {
    delay_seconds: number
}

///////////////////////////////////////////////////////////////////////////////
// Edges - sync with plugin-server/src/types.ts
///////////////////////////////////////////////////////////////////////////////
export type WorkflowEdge = Edge<WorkflowEdgeData, WorkflowEdgeType>
export type WorkflowEdgeType = 'default' | 'condition_match'
export interface WorkflowEdgeData extends Record<string, unknown> {
    label?: string
    config: WorkflowEdgeConfig
}
export type WorkflowEdgeConfig = DefaultEdgeConfig | ConditionMatchEdgeConfig

// No config needed for default edges yet
export type DefaultEdgeConfig = Record<string, never>

// Condition match edges need to know the match type and the conditions
export type ConditionMatchEdgeConfig = {
    match_type: 'all' | 'any'
    condition: WorkflowPropertyFilter[]
}

///////////////////////////////////////////////////////////////////////////////
// Common types - sync with plugin-server/src/types.ts
///////////////////////////////////////////////////////////////////////////////
export type WorkflowPropertyFilter = EventPropertyFilter | PersonPropertyFilter
export type WorkflowPropertyFilterMatchType = 'all' | 'any'

export type WorkflowFilters = {
    match_type: WorkflowPropertyFilterMatchType
    properties: WorkflowPropertyFilter[]
}
