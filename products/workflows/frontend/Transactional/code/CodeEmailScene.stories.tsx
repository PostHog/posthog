import { Meta, StoryFn } from '@storybook/react'
import { BindLogic } from 'kea'

import { useStorybookMocks } from '~/mocks/browser'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { codeEmailLogic } from './codeEmailLogic'
import { CodeEmailScene } from './CodeEmailScene'

const passwordReset: CodeEmailApi = {
    id: '0190a1b2-0000-7000-8000-0000000000c1',
    key: 'password-reset',
    hog_flow_id: '0190a1b2-0000-7000-8000-0000000000f1',
    description: 'Sent when someone asks to reset their password',
    tags: ['auth'],
    sensitive: true,
    source_url:
        'https://github.com/acme/web/blob/4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39/src/emails/password-reset.tsx',
    created_at: '2026-11-01T10:00:00Z',
    user_access_level: 'editor',
}

const meta: Meta = {
    title: 'Products/Workflows/CodeEmailScene',
    component: CodeEmailScene,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        testOptions: { waitForSelector: '[data-attr="code-email-scene"]', snapshotBrowsers: [] },
    },
}
export default meta

const Template: StoryFn<{ codeEmail: CodeEmailApi }> = ({ codeEmail }) => {
    useStorybookMocks({
        get: { [`/api/projects/:team_id/transactional_code_emails/${codeEmail.id}/`]: codeEmail },
    })
    return (
        <BindLogic logic={codeEmailLogic} props={{ id: codeEmail.id }}>
            <CodeEmailScene />
        </BindLogic>
    )
}

export const LinkedToASourceFile = Template.bind({})
LinkedToASourceFile.args = { codeEmail: passwordReset }

export const NoSourceFileYet = Template.bind({})
NoSourceFileYet.args = {
    codeEmail: {
        ...passwordReset,
        id: '0190a1b2-0000-7000-8000-0000000000c3',
        key: 'order-shipped',
        description: '',
        tags: [],
        source_url: null,
    },
}
