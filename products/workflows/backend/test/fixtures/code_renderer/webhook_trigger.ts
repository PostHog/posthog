import { delay, path, trigger, workflow } from '@posthog/workflows'

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
            },
        },
        { name: 'Webhook trigger', description: 'A webhook starts this workflow.' },
    ),
    steps: path(delay('1d', { name: 'Wait a day' })),
    exit: { reason: 'Done', description: 'The webhook workflow finished.' },
})
