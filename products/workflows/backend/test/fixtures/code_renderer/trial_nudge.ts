// @posthog/workflows cannot express everything in this workflow. Review these before you push:
// - trigger_node: The trigger filters out test accounts. @posthog/workflows cannot set that, so a push turns it off.
// - exit_node: The exit condition "exit_on_conversion" needs a conversion goal, which @posthog/workflows cannot declare. The workflow exits only at the end.

import { delay, email, onEvent, path, workflow } from '@posthog/workflows'

export const trialNudgeV2 = workflow({
    key: 'trial-nudge-v2',
    name: 'Trial nudge (v2)',
    status: 'draft',
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
