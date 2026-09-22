import { delay, email, onEvent, path, workflow } from '@posthog/workflows'

export const welcomeEmail = workflow({
    key: 'welcome-email',
    name: 'Welcome email',
    status: 'draft',
    on: onEvent({ event: 'user signed up' }),
    steps: path(
        delay('1d', {
            name: 'Delay',
            description: 'Wait for 1 day.',
            id: 'action_delay_0199e2c6-2a1b-7c3d-8e4f-000000000001',
        }),
        email({
            name: 'Email',
            description: 'Send an email to the user.',
            id: 'action_function_email_0199e2c6-2a1b-7c3d-8e4f-000000000002',
            from: { integrationIds: [4] },
            to: '{{ person.properties.email }}',
            subject: 'Welcome',
            text: 'Welcome aboard.',
            html: '<p>Welcome aboard.</p>',
        }),
    ),
    exit: { reason: 'Reached the end' },
})
