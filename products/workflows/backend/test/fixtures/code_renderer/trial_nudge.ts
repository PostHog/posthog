// @posthog/workflows cannot express everything in this workflow. Review these before you push:
// - This workflow has no key, so the copied file invents one from its name. The first push creates a new draft workflow. Turn the original workflow off or delete it after that push.

import { delay, email, path, trigger, workflow } from '@posthog/workflows'

export const trialNudgeV2 = workflow({
    key: 'trial-nudge-v2',
    name: 'Trial nudge (v2)',
    status: 'draft',
    on: trigger(
        {
            type: 'event',
            filters: {
                events: [
                    { id: '$pageview', name: '$pageview', type: 'events', order: 0, properties: [] },
                ],
                properties: [],
                filter_test_accounts: true,
            },
        },
        { name: 'trigger_1' },
    ),
    steps: path(
        delay('2h', { name: 'Wait 2 hours', id: 'action_1' }),
        email({
            name: 'Send a nudge',
            id: 'action_2',
            from: { integrationIds: [3], email: 'hello@example.com', name: 'Example' },
            to: '{person.properties.email}',
            subject: 'Still there?',
            text: 'Your trial has a week left.',
            html: '<p>Your trial has a week left.</p>',
        }),
    ),
    exit: { reason: 'Reached the end' },
})
