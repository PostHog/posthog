// @posthog/workflows cannot express everything in this workflow. Review these before you push:
// - Pass-through steps: which_plan (Which plan?).
// - tell_the_crm: The input "signing_secret" of "Tell the CRM" is a secret. PostHog does not return its value, so set TELL_THE_CRM_SIGNING_SECRET before you push.

import { delay, eventProperty, onEvent, path, secret, step, webhook, workflow } from '@posthog/workflows'

const tellTheCrm = webhook({
    name: 'Tell the CRM',
    description: 'Push the deal to the CRM.',
    url: 'https://example.com/hooks/crm',
    body: { distinct_id: '{event.distinct_id}', plan: '{person.properties.plan}' },
    signingSecret: secret('TELL_THE_CRM_SIGNING_SECRET'),
})

export const crmFollowUp = workflow({
    key: 'crm-follow-up',
    name: 'CRM follow up',
    on: onEvent({
        event: 'checkout completed',
        properties: [eventProperty('total', 'gt', [100])],
    }),
    steps: path(
        tellTheCrm,
        step({
            name: 'Which plan?',
            description: 'Split the path on the plan the person is on.',
            type: 'conditional_branch',
            config: {
                conditions: [
                    {
                        name: 'Paid plan',
                        filters: {
                            properties: [{ key: 'plan', operator: 'exact', value: ['pro'], type: 'person' }],
                            bytecode: ['_H', 1, 32, 'pro', 32, 'plan', 32, 'properties', 32, 'person', 1, 3, 11],
                        },
                    },
                    {
                        name: 'Came from pricing',
                        filters: {
                            properties: [
                                {
                                    key: '$current_url',
                                    operator: 'icontains',
                                    value: ['/pricing'],
                                    type: 'event',
                                },
                            ],
                            bytecode: ['_H', 1, 32, '%/pricing%', 32, '$current_url', 32, 'properties', 1, 2, 17],
                        },
                    },
                ],
            },
            branches: [
                path(delay('1d', { name: 'Give sales a day' }), tellTheCrm),
                path(delay('7d', { name: 'Wait a week' })),
            ],
        }),
    ),
    exit: { reason: 'Handed to sales' },
})
