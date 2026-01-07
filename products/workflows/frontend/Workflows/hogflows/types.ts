import { Edge, Node } from '@xyflow/react'
import { z } from 'zod'

import { CyclotronJobInputsValidationResult } from 'lib/components/CyclotronJob/CyclotronJobInputsValidation'

import { UserBasicType } from '~/types'

import { CyclotronJobInputSchemaTypeSchema, HogFlowActionSchema, HogFlowTriggerSchema } from './steps/types'

const HogFlowEdgeSchema = z.object({
    from: z.string(),
    to: z.string(),
    type: z.enum(['continue', 'branch']),
    index: z.number().optional(),
})

export const HogFlowSchema = z.object({
    id: z.string(),
    team_id: z.number(),
    version: z.number(),
    name: z.string(),
    description: z.string().optional(),
    status: z.enum(['active', 'draft', 'archived']),
    trigger: HogFlowTriggerSchema.optional(),
    // Optional masking config for the trigger, allows HogFlows to be rate limited per distinct ID or other property
    trigger_masking: z
        .object({
            ttl: z.number().nullable(),
            hash: z.string(),
            bytecode: z.array(z.union([z.string(), z.number()])),
            threshold: z.number().nullable(),
        })
        .optional()
        .nullable(),
    conversion: z
        .object({
            window_minutes: z.number(),
            filters: z.any(),
        })
        .optional(),
    exit_condition: z.enum([
        'exit_on_conversion',
        'exit_on_trigger_not_matched',
        'exit_on_trigger_not_matched_or_conversion',
        'exit_only_at_end',
    ]),
    actions: z.array(HogFlowActionSchema),
    abort_action: z.string().optional(),
    edges: z.array(HogFlowEdgeSchema),
    variables: z.array(CyclotronJobInputSchemaTypeSchema).optional().nullable(),
    updated_at: z.string(),
    created_at: z.string(),
})

export const HogFlowTemplateSchema = HogFlowSchema.omit({ status: true }).extend({
    image_url: z.string().optional().nullable(),
    scope: z.enum(['team', 'global']).optional().nullable(),
})

export const HogFlowBatchJobSchema = z.object({
    id: z.string(),
    team_id: z.number(),
    hog_flow_id: z.string(),
    variables: z.record(z.any()),
    status: z.enum(['waiting', 'queued', 'active', 'completed', 'cancelled', 'failed']),
    scheduled_at: z.string().nullable(),
    created_at: z.string(),
    updated_at: z.string(),
})

// NOTE: these are purposefully exported as interfaces to support kea typegen
export interface HogFlow extends z.infer<typeof HogFlowSchema> {
    created_by?: UserBasicType | null
}
export interface HogFlowEdge extends z.infer<typeof HogFlowEdgeSchema> {}
export interface HogFlowActionEdge extends Edge<{ edge: HogFlowEdge; label?: string }> {}

export type HogFlowAction = z.infer<typeof HogFlowActionSchema> & Record<string, unknown>
export interface HogFlowActionNode extends Node<HogFlowAction> {}

// Dropzone nodes are ephemeral and on the client only, used in the editor to highlight where nodes can be added to a workflow
export type DropzoneNode = Node<{ edge: HogFlowActionEdge; isBranchJoinDropzone?: boolean }>

export type HogFlowActionValidationResult = CyclotronJobInputsValidationResult & {
    schema: z.ZodError | null
}

export interface HogFlowTemplate extends z.infer<typeof HogFlowTemplateSchema> {
    created_by?: UserBasicType | null
}

export interface HogFlowBatchJob extends z.infer<typeof HogFlowBatchJobSchema> {
    created_by?: UserBasicType | null
}
