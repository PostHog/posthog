// @posthog/workflows cannot express everything in this workflow. Review these before you push:
// - tell_the_crm: The input "signing_secret" of "Tell the CRM" is a secret. PostHog does not return its value, so set TELL_THE_CRM_SIGNING_SECRET before you push.

import { branch, delay, eventProperty, onEvent, path, person, secret, webhook, workflow } from '@posthog/workflows'

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
        branch({
            name: 'Which plan?',
            description: 'Split the path on the plan the person is on.',
            branches: [
                {
                    name: 'Paid plan',
                    when: [person('plan', 'exact', ['pro'])],
                    then: path(delay('1d', { name: 'Give sales a day' }), tellTheCrm),
                },
                {
                    name: 'Came from pricing',
                    when: [eventProperty('$current_url', 'icontains', ['/pricing'])],
                    then: path(delay('7d', { name: 'Wait a week' })),
                },
            ],
        }),
    ),
    exit: { reason: 'Handed to sales' },
})
