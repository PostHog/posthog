import { Meta, StoryFn } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { TransactionalEmailsTable } from './TransactionalEmailsTable'

const templates = {
    count: 2,
    next: null,
    previous: null,
    results: [
        {
            id: '0190a1b2-0000-7000-8000-000000000001',
            name: 'Welcome',
            description: 'Sent after someone signs up',
            tags: ['onboarding'],
            sensitive: false,
            transactional_hog_flow_id: '0190a1b2-0000-7000-8000-0000000000f1',
            created_by: { id: 1, uuid: 'user-1', first_name: 'Ava', email: 'ava@example.com' },
            created_at: '2026-10-01T10:00:00Z',
            updated_at: '2026-11-02T10:00:00Z',
            deleted: false,
        },
        {
            id: '0190a1b2-0000-7000-8000-000000000002',
            name: 'Sign-in code',
            description: '',
            tags: ['auth'],
            sensitive: true,
            transactional_hog_flow_id: '0190a1b2-0000-7000-8000-0000000000f2',
            created_by: { id: 2, uuid: 'user-2', first_name: 'Ben', email: 'ben@example.com' },
            created_at: '2026-09-01T10:00:00Z',
            updated_at: '2026-10-20T10:00:00Z',
            deleted: false,
        },
    ],
}

const codeEmail = (id: string, key: string, fields: Partial<CodeEmailApi>): CodeEmailApi => ({
    id,
    key,
    hog_flow_id: `0190a1b2-0000-7000-8000-0000000000c${id}`,
    description: '',
    tags: [],
    sensitive: true,
    source_url: null,
    source_origin: null,
    created_at: '2026-11-01T10:00:00Z',
    user_access_level: 'editor',
    ...fields,
})

const codeEmails: CodeEmailApi[] = [
    codeEmail('1', 'password-reset', {
        description: 'Sent when someone asks to reset their password',
        tags: ['auth'],
        source_url: 'https://github.com/acme/web/blob/main/src/emails/password-reset.tsx',
        source_origin: 'manual',
    }),
    codeEmail('2', 'invoice-paid', {
        tags: ['billing'],
        source_url: 'https://gitlab.com/acme/platform/billing/-/blob/main/app/mailers/invoice_paid.rb',
        source_origin: 'manual',
    }),
    codeEmail('3', 'order-shipped', {}),
]

const meta: Meta = {
    title: 'Products/Workflows/TransactionalEmailsTable',
    component: TransactionalEmailsTable,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        testOptions: { waitForSelector: '[data-attr="transactional-emails-table"]', snapshotBrowsers: [] },
    },
}
export default meta

export const TemplatesAndEmailsSentFromCode: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/messaging_templates/': templates,
            '/api/projects/:team_id/transactional_code_emails/': codeEmails,
            '/api/projects/:team_id/tags': ['auth', 'billing', 'onboarding'],
        },
    })
    return <TransactionalEmailsTable />
}
