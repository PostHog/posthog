import { Handle, Node, NodeProps } from '@xyflow/react'

import { Optional } from '~/types'

import { z } from 'zod'
import { HogFlowAction } from '../types'

export type HogFlowStepNodeProps = NodeProps & {
    data: HogFlowAction
    type: HogFlowAction['type']
}

export type StepViewNodeHandle = Omit<Optional<Handle, 'width' | 'height'>, 'nodeId'> & { label?: string }

export type HogFlowStep<T extends HogFlowAction['type']> = {
    type: T
    name: string
    description: string
    icon: JSX.Element
    color: string
    renderNode: (props: HogFlowStepNodeProps) => JSX.Element
    renderConfiguration: (node: Node<Extract<HogFlowAction, { type: T }>>) => JSX.Element
    create: () => {
        action: Pick<Extract<HogFlowAction, { type: T }>, 'config' | 'name' | 'description'>
        branchEdges?: number
    }
}

const _commonActionFields = {
    id: z.string(),
    name: z.string(),
    description: z.string(),
    on_error: z.enum(['continue', 'abort', 'complete', 'branch']).optional(),
    created_at: z.number(),
    updated_at: z.number(),
    filters: z.any(), // TODO: Correct to the right type
}

const CyclotronInputSchema = z.object({
    value: z.any(),
    templating: z.enum(['hog', 'liquid']).optional(),
    secret: z.boolean().optional(),
    bytecode: z.any().optional(),
    order: z.number().optional(),
})

export const HogFlowActionSchema = z.discriminatedUnion('type', [
    // Trigger
    z.object({
        ..._commonActionFields,
        type: z.literal('trigger'),
        config: z.object({
            type: z.literal('event'),
            filters: z.any(),
        }),
        // A trigger's event filters are stored on the top-level Hogflow object
    }),
    // Branching
    z.object({
        ..._commonActionFields,
        type: z.literal('conditional_branch'),
        config: z.object({
            conditions: z.array(
                z.object({
                    filters: z.any(), // type this stronger
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
                filters: z.any(), // type this stronger
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

    // Native messages
    z.object({
        ..._commonActionFields,
        type: z.literal('function_email'),
        config: z.object({
            message_category: z.string().optional(),
            template_uuid: z.string().optional(), // May be used later to specify a specific template version
            template_id: z.literal('template-email-native'),
            inputs: z.record(CyclotronInputSchema),
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
        type: z.literal('function_sms'),
        config: z.object({
            template_uuid: z.string().uuid().optional(),
            template_id: z.literal('template-twilio'),
            inputs: z.record(CyclotronInputSchema),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('function_slack'),
        config: z.object({
            template_uuid: z.string().uuid().optional(),
            template_id: z.literal('template-slack'),
            inputs: z.record(CyclotronInputSchema),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('function_webhook'),
        config: z.object({
            template_uuid: z.string().uuid().optional(),
            template_id: z.literal('template-webhook'),
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
