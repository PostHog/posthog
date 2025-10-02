import { Node } from '@xyflow/react'
import { z } from 'zod'

import { CyclotronJobInputsValidationResult } from 'lib/components/CyclotronJob/CyclotronJobInputsValidation'

import { HogFlowActionSchema, HogFlowTriggerSchema } from './steps/types'

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
    updated_at: z.string(),
    created_at: z.string(),
})

// NOTE: these are purposefully exported as interfaces to support kea typegen
export interface HogFlow extends z.infer<typeof HogFlowSchema> {}
export interface HogFlowEdge extends z.infer<typeof HogFlowEdgeSchema> {}
export type HogFlowAction = z.infer<typeof HogFlowActionSchema> & Record<string, unknown>
export interface HogFlowActionNode extends Node<HogFlowAction> {}

export type HogFlowActionValidationResult = CyclotronJobInputsValidationResult & {
    schema: z.ZodError | null
}
