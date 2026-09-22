import { branch, delay, email, onEvent, path, person, workflow } from '@posthog/workflows'

const welcomeEmail = email({
    name: 'Send the welcome email',
    // The id of the project's verified email sender, listed under Workflows, Channels.
    from: { integrationIds: [1] },
    to: '{person.properties.email}',
    subject: 'Welcome to PostHog',
    text: 'Thanks for signing up. Your first events show up in Activity as soon as your SDK sends them.',
    html: '<p>Thanks for signing up. Your first events show up in Activity as soon as your SDK sends them.</p>',
})

export const welcomeNewSignups = workflow({
    key: 'welcome-new-signups',
    name: 'Welcome new signups',
    description: 'Sends a welcome email a day after signup to people who have an email address.',
    // Stays draft so a push never sends an email to anyone.
    status: 'draft',
    on: onEvent({ event: 'user signed up' }),
    steps: path(
        delay('1d', { name: 'Wait a day' }),
        branch({
            name: 'Has an email address?',
            branches: [{ name: 'Has an email address', when: [person('email', 'is_set')], then: path(welcomeEmail) }],
        })
    ),
    exit: { reason: 'Welcome new signups finished' },
})
