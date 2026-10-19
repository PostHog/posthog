import { templateToConfiguration } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'

import { HogFunctionTemplateType } from '~/types'

import type { HogFlow, HogFlowAction } from '../Workflows/hogflows/types'

// Template categories split these tools across "Email Marketing", "Customer Success" and "Communication",
// so the list is explicit.
export const MESSAGING_DESTINATION_TEMPLATE_IDS: ReadonlySet<string> = new Set([
    'template-activecampaign',
    'template-beehiiv',
    'template-braze',
    'template-brevo',
    'template-customerio',
    'template-discord',
    'template-engage-so',
    'template-intercom',
    'template-intercom-event',
    'template-klaviyo-event',
    'template-klaviyo-user',
    'template-knock',
    'template-kudosity-sms',
    'template-loops',
    'template-loops-event',
    'template-mailgun-send-email',
    'template-mailjet-create-contact',
    'template-mailjet-update-contact-list',
    'template-microsoft-teams',
    'template-onesignal',
    'template-sendgrid',
    'template-slack',
    'template-userlist',
    'template-whatsapp',
])

// Same values as TRIGGER_NODE_ID and EXIT_NODE_ID in workflowLogic. Importing them would pull the editor into the
// destinations scene.
const TRIGGER_NODE_ID = 'trigger_node'
const EXIT_NODE_ID = 'exit_node'
export const DESTINATION_STEP_ID = 'action_function_destination'

export type DestinationWorkflowDraft = Pick<HogFlow, 'name' | 'status' | 'exit_condition' | 'actions' | 'edges'>

export function isMessagingDestinationTemplate(templateId: string): boolean {
    return MESSAGING_DESTINATION_TEMPLATE_IDS.has(templateId)
}

/** A draft workflow that runs the template as its only step, between an event trigger and the exit. */
export function buildDestinationWorkflow(template: HogFunctionTemplateType): DestinationWorkflowDraft {
    const actions: HogFlowAction[] = [
        {
            id: TRIGGER_NODE_ID,
            type: 'trigger',
            name: 'Trigger',
            description: 'User performs an action to start the workflow.',
            created_at: 0,
            updated_at: 0,
            config: { type: 'event', filters: {} },
        },
        {
            id: DESTINATION_STEP_ID,
            type: 'function',
            name: template.name,
            description: typeof template.description === 'string' ? template.description : '',
            created_at: 0,
            updated_at: 0,
            // The step editor reads its inputs once on mount, so the template defaults go in now.
            config: { template_id: template.id, inputs: templateToConfiguration(template).inputs ?? {} },
        },
        {
            id: EXIT_NODE_ID,
            type: 'exit',
            name: 'Exit',
            description: 'User moved through the workflow without errors.',
            created_at: 0,
            updated_at: 0,
            config: { reason: 'Default exit' },
        },
    ]
    return {
        name: `${template.name} workflow`,
        status: 'draft',
        exit_condition: 'exit_only_at_end',
        actions,
        edges: [
            { from: TRIGGER_NODE_ID, to: DESTINATION_STEP_ID, type: 'continue' },
            { from: DESTINATION_STEP_ID, to: EXIT_NODE_ID, type: 'continue' },
        ],
    }
}
