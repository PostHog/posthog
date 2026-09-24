// @posthog/workflows cannot express everything in this workflow. Review these before you push:
// - trigger_node: The input "auth_header" of "Webhook trigger" is a secret. PostHog does not return its value, so set TRIGGER_NODE_AUTH_HEADER before you push.

import { delay, path, secret, trigger, workflow } from '@posthog/workflows'

export const webhookTrigger = workflow({
    key: 'webhook-trigger',
    name: 'Webhook trigger',
    on: trigger(
        {
            type: 'webhook',
            template_id: 'template-source-webhook',
            inputs: {
                event: { value: '{request.body.event}', order: 0 },
                distinct_id: { value: '{request.body.distinct_id}', order: 1 },
                auth_header: secret('TRIGGER_NODE_AUTH_HEADER'),
            },
        },
        { name: 'Webhook trigger', description: 'A webhook starts this workflow.' },
    ),
    steps: path(delay('1d', { name: 'Wait a day' })),
    exit: { reason: 'Done', description: 'The webhook workflow finished.' },
})
