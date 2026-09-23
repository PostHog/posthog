// @posthog/workflows cannot express everything in this workflow. Review these before you push:
// - This workflow has no key, so the copied file invents one from its name. The first push creates a new draft workflow. Turn the original workflow off or delete it after that push.
// - trigger_node: The trigger filters out test accounts. @posthog/workflows cannot set that, so a push turns it off.

import { delay, email, onEvent, path, workflow } from '@posthog/workflows'

export const trialNudgeV2 = workflow({
    key: 'trial-nudge-v2',
    name: 'Trial nudge (v2)',
    on: onEvent({ event: '$pageview' }),
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
