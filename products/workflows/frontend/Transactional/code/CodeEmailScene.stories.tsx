import { Meta, StoryFn } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/dom'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import type { CodeEmailApi, CodeEmailSourceCandidatesApi } from 'products/messaging/frontend/generated/api.schemas'

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
    source_origin: 'manual',
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

const githubIntegration = {
    id: 7,
    kind: 'github',
    display_name: 'acme',
    icon_url: '',
    config: { account: { type: 'Organization', name: 'acme' } },
    created_at: '2026-10-01T10:00:00Z',
}

const sourceCandidates: CodeEmailSourceCandidatesApi = {
    candidates: [
        {
            repository: 'acme/web',
            path: 'src/emails/order-shipped.tsx',
            line: 18,
            url: 'https://github.com/acme/web/blob/HEAD/src/emails/order-shipped.tsx#L18',
            call_site: true,
        },
        {
            repository: 'acme/api',
            path: 'app/mail/keys.py',
            line: 7,
            url: 'https://github.com/acme/api/blob/HEAD/app/mail/keys.py#L7',
            call_site: false,
        },
    ],
    complete: true,
}

const noLink: CodeEmailApi = {
    ...passwordReset,
    id: '0190a1b2-0000-7000-8000-0000000000c3',
    key: 'order-shipped',
    description: '',
    tags: [],
    source_url: null,
    source_origin: null,
}

const Template: StoryFn<{
    codeEmail: CodeEmailApi
    github?: boolean
    candidates?: CodeEmailSourceCandidatesApi
}> = ({ codeEmail, github = false, candidates = sourceCandidates }) => {
    useStorybookMocks({
        get: {
            [`/api/projects/:team_id/transactional_code_emails/${codeEmail.id}/`]: codeEmail,
            [`/api/projects/:team_id/transactional_code_emails/${codeEmail.id}/source_candidates/`]: candidates,
            '/api/projects/:team_id/integrations/': {
                count: github ? 1 : 0,
                next: null,
                previous: null,
                results: github ? [githubIntegration] : [],
            },
        },
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
NoSourceFileYet.args = { codeEmail: noLink }

const withSourceDetection = { featureFlags: [FEATURE_FLAGS.WORKFLOWS_CODE_EMAIL_SOURCE_DETECTION] }

export const DetectedFromGitHub = Template.bind({})
DetectedFromGitHub.args = {
    codeEmail: {
        ...passwordReset,
        id: '0190a1b2-0000-7000-8000-0000000000c4',
        source_url: 'https://github.com/acme/web/blob/HEAD/src/emails/password-reset.tsx#L24',
        source_origin: 'detected',
    },
    github: true,
}
DetectedFromGitHub.parameters = withSourceDetection

export const NoSourceFileWithGitHub = Template.bind({})
NoSourceFileWithGitHub.args = { codeEmail: noLink, github: true }
NoSourceFileWithGitHub.parameters = {
    ...withSourceDetection,
    testOptions: { waitForSelector: '[data-attr="code-email-find-source-in-github"]', snapshotBrowsers: [] },
}

const openPicker: StoryFn['play'] = async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    fireEvent.click(await canvas.findByText('Find in GitHub'))
    await waitFor(() => {
        const picker = document.querySelector('[data-attr="code-email-source-picker"]')
        if (!picker || picker.querySelector('.Spinner')) {
            throw new Error('The picker is still searching')
        }
    })
}

export const PickerWithCandidates = Template.bind({})
PickerWithCandidates.args = { codeEmail: noLink, github: true }
PickerWithCandidates.parameters = NoSourceFileWithGitHub.parameters
PickerWithCandidates.play = openPicker

export const PickerFoundNothing = Template.bind({})
PickerFoundNothing.args = { codeEmail: noLink, github: true, candidates: { candidates: [], complete: true } }
PickerFoundNothing.parameters = NoSourceFileWithGitHub.parameters
PickerFoundNothing.play = openPicker
