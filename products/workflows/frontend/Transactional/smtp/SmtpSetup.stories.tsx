import { Meta, StoryFn } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import type { SmtpSetupApi } from 'products/messaging/frontend/generated/api.schemas'

import { SmtpSetup } from './SmtpSetup'

const meta: Meta<typeof SmtpSetup> = {
    title: 'Scenes-App/Transactional/SMTP setup',
    component: SmtpSetup,
    parameters: { mockDate: '2026-11-06', testOptions: { snapshotBrowsers: [] } },
}
export default meta

const SETUP: SmtpSetupApi = {
    host: 'smtp.example.com',
    username: 'posthog',
    ports: [
        { port: 465, security: 'tls', alternate: false },
        { port: 587, security: 'starttls', alternate: false },
        { port: 2465, security: 'tls', alternate: true },
        { port: 2587, security: 'starttls', alternate: true },
    ],
    activity: [
        {
            kind: 'refused',
            reply: '550 5.7.1 No verified sender in this project can send from `jane@example.org`.',
            from: 'jane@example.org',
            to: ['maya@example.com'],
            at: 1793923200,
        },
        {
            kind: 'dropped_headers',
            from: 'jane@example.com',
            to: ['maya@example.com', 'sam@example.com', 'alex@example.com'],
            dropped_headers: ['Sender', 'Precedence'],
            at: 1793919600,
        },
    ],
}

export const WithRecentProblems: StoryFn = () => {
    useStorybookMocks({ get: { '/api/projects/:team_id/messaging/smtp/setup/': SETUP } })
    return <SmtpSetup />
}

export const NoRelayOnThisInstance: StoryFn = () => {
    useStorybookMocks({ get: { '/api/projects/:team_id/messaging/smtp/setup/': { ...SETUP, host: '', activity: [] } } })
    return <SmtpSetup />
}
