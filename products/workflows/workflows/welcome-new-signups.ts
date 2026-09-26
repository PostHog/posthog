import { branch, delay, email, onEvent, path, person, workflow } from '@posthog/workflows'

const SENDER_VARIABLE = 'POSTHOG_WORKFLOWS_EMAIL_INTEGRATION_ID'

function senderIntegrationId(): number {
    const raw = process.env[SENDER_VARIABLE]?.trim() ?? ''
    if (!/^[1-9][0-9]*$/.test(raw)) {
        throw new Error(
            `Set ${SENDER_VARIABLE} to the id of an email integration in the project you push to. Find the id under Workflows, Channels, in that project. repo:check sets a stand-in id when the variable is not set.`
        )
    }
    return Number(raw)
}

const welcomeEmail = email({
    name: 'Send the welcome email',
    from: { integrationIds: [senderIntegrationId()] },
    to: '{person.properties.email}',
    subject: 'Welcome to PostHog',
    text: 'Thanks for signing up. Your first events show up in Activity as soon as your SDK sends them.',
    html: '<p>Thanks for signing up. Your first events show up in Activity as soon as your SDK sends them.</p>',
})

export const welcomeNewSignups = workflow({
    key: 'welcome-new-signups',
    name: 'Welcome new signups',
    description: 'Sends a welcome email a day after signup to people who have an email address.',
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
