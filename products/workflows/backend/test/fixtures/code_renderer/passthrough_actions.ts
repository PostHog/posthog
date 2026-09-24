// @posthog/workflows cannot express everything in this workflow. Review these before you push:
// - Pass-through steps: send_sms (Send SMS), split (Split traffic), wait_for_office_hours (Wait for office hours).
// - split: The arm "1" of "Split traffic" has no edge. Add a step to it before you push.
// - split: The branch arm 1 of "Split traffic" has no steps, so it is dropped. A person who matches it continues after the branch either way.

import { onEvent, path, step, workflow } from '@posthog/workflows'

export const passthroughActions = workflow({
    key: 'passthrough-actions',
    name: 'Pass-through actions',
    on: onEvent({ event: 'signed_up', description: 'User starts this workflow.' }),
    steps: path(
        step({
            name: 'Send SMS',
            type: 'function_sms',
            config: {
                template_id: 'template-twilio',
                inputs: {
                    to_number: { value: '{person.properties.phone}', order: 0 },
                    message: { value: 'Welcome!', order: 1 },
                },
            },
        }),
        step({
            name: 'Split traffic',
            id: 'split',
            type: 'random_cohort_branch',
            config: { cohorts: [{ percentage: 50, name: 'A' }, { percentage: 50, name: 'B' }] },
            branches: [
                path(
                    step({
                        name: 'Wait for office hours',
                        type: 'wait_until_time_window',
                        config: { timezone: 'UTC', day: 'weekday', time: ['09:00', '17:00'] },
                    }),
                ),
            ],
        }),
    ),
    exit: { reason: 'Done', description: 'The workflow finished.' },
})
