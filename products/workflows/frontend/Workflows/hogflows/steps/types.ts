import { Handle, NodeProps } from '@xyflow/react'
import { z } from 'zod'

import { LogEntry } from 'scenes/hog-functions/logs/logsViewerLogic'

import { Optional } from '~/types'

import { HogFlowAction } from '../types'

export type HogFlowStepNodeProps = NodeProps & {
    data: HogFlowAction
    type: HogFlowAction['type']
}

export type StepViewNodeHandle = Omit<Optional<Handle, 'width' | 'height'>, 'nodeId'> & { label?: string }

const ActionFiltersSchema = z.object({
    events: z.array(z.any()).optional(),
    properties: z.array(z.any()).optional(),
    actions: z.array(z.any()).optional(),
})

const _commonActionFields = {
    id: z.string(),
    name: z.string(),
    description: z.string(),
    on_error: z.enum(['continue', 'abort']).optional().nullable(),
    created_at: z.number(),
    updated_at: z.number(),
    filters: ActionFiltersSchema.optional().nullable(),
}

const CyclotronInputSchema = z.object({
    value: z.any(),
    templating: z.enum(['hog', 'liquid']).optional(),
    secret: z.boolean().optional(),
    bytecode: z.any().optional(),
    order: z.number().optional(),
})

export type CyclotronInputType = z.infer<typeof CyclotronInputSchema>

export const HogFlowTriggerSchema = z.discriminatedUnion('type', [
    z.object({
        type: z.literal('event'),
        filters: ActionFiltersSchema,
    }),
    z.object({
        type: z.literal('webhook'),
        template_uuid: z.string().uuid().optional(), // May be used later to specify a specific template version
        template_id: z.string(),
        inputs: z.record(CyclotronInputSchema),
    }),
    z.object({
        type: z.literal('manual'),
        template_uuid: z.string().uuid().optional(), // May be used later to specify a specific template version
        template_id: z.string(),
        inputs: z.record(CyclotronInputSchema),
    }),
    z.object({
        type: z.literal('tracking_pixel'),
        template_uuid: z.string().uuid().optional(), // May be used later to specify a specific template version
        template_id: z.string(),
        inputs: z.record(CyclotronInputSchema),
    }),
])

export const HogFlowActionSchema = z.discriminatedUnion('type', [
    // Trigger
    z.object({
        ..._commonActionFields,
        type: z.literal('trigger'),
        config: HogFlowTriggerSchema,
    }),
    // Branching
    z.object({
        ..._commonActionFields,
        type: z.literal('conditional_branch'),
        config: z.object({
            conditions: z.array(
                z.object({
                    filters: ActionFiltersSchema,
                })
            ),
            delay_duration: z.string().optional(),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('random_cohort_branch'),
        config: z.object({
            cohorts: z.array(
                z.object({
                    percentage: z.number(),
                })
            ),
        }),
    }),

    // Time based
    z.object({
        ..._commonActionFields,
        type: z.literal('delay'),
        config: z.object({
            delay_duration: z.string().min(2),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('wait_until_condition'),
        config: z.object({
            condition: z.object({
                filters: ActionFiltersSchema.optional().nullable(),
            }),
            max_wait_duration: z.string(),
        }),
    }),

    z.object({
        ..._commonActionFields,
        type: z.literal('wait_until_time_window'),
        config: z.object({
            timezone: z.string().nullable(),
            // Day can be special values "weekday", "weekend" or a list of days of the week e.g. 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
            day: z.union([
                z.literal('any'),
                z.literal('weekday'),
                z.literal('weekend'),
                z.array(z.enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])),
            ]),
            // time can be "any", or a time range [start, end]
            time: z.union([
                z.literal('any'),
                z.tuple([z.string(), z.string()]), // e.g. ['10:00', '11:00']
            ]),
        }),
    }),

    // CDP functions
    z.object({
        ..._commonActionFields,
        type: z.literal('function'),
        config: z.object({
            template_uuid: z.string().uuid().optional(), // May be used later to specify a specific template version
            template_id: z.string(),
            inputs: z.record(CyclotronInputSchema),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('function_email'),
        config: z.object({
            message_category_id: z.string().uuid().optional(),
            template_uuid: z.string().optional(), // May be used later to specify a specific template version
            template_id: z.literal('template-email'),
            inputs: z.record(CyclotronInputSchema),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('function_sms'),
        config: z.object({
            message_category_id: z.string().uuid().optional(),
            template_uuid: z.string().uuid().optional(),
            template_id: z.literal('template-twilio'),
            inputs: z.record(CyclotronInputSchema),
        }),
    }),

    // Exit
    z.object({
        ..._commonActionFields,
        type: z.literal('exit'),
        config: z.object({
            reason: z.string().optional(),
        }),
    }),
])

export const isOptOutEligibleAction = (
    action: HogFlowAction
): action is Extract<HogFlowAction, { type: 'function_email' | 'function_sms' }> => {
    return ['function_email', 'function_sms'].includes(action.type)
}

export const isFunctionAction = (
    action: HogFlowAction
): action is Extract<HogFlowAction, { type: 'function' | 'function_sms' | 'function_email' }> => {
    return ['function', 'function_sms', 'function_email'].includes(action.type)
}

export const isTriggerFunction = (
    action: HogFlowAction
): action is Extract<HogFlowAction, { type: 'trigger'; config: { type: 'webhook' | 'manual' | 'tracking_pixel' } }> => {
    if (action.type !== 'trigger') {
        return false
    }
    const trigger = action as Extract<HogFlowAction, { type: 'trigger' }>
    return ['webhook', 'tracking_pixel'].includes(trigger.config.type)
}

export interface HogflowTestResult {
    status: 'success' | 'error' | 'skipped'
    logs?: LogEntry[]
    nextActionId: string | null
    errors?: string[]
}
