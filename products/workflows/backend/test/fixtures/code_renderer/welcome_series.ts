import { delay, email, onEvent, path, workflow } from '@posthog/workflows'

export const welcomeSeries = workflow({
    key: 'welcome-series',
    name: 'Welcome series',
    description: 'Greets a new signup a day later.',
    on: onEvent({ event: 'user signed up' }),
    steps: path(
        delay('1d', {
            name: 'Wait a day',
            description: 'Gives a new signup a day before the first email.',
        }),
        email({
            name: 'Send the welcome email',
            from: { integrationIds: [12], name: 'The Example team' },
            to: '{person.properties.email}',
            subject: 'Welcome aboard',
            text: 'Thanks for signing up.',
            html: '<p>Thanks for signing up.</p>',
        }),
    ),
    exit: { reason: 'Done' },
})
