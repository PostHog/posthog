import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import { messageTemplateLogic } from './messageTemplateLogic'
import { messageTemplateTestSendLogic } from './messageTemplateTestSendLogic'
import { SendTestEmailModal } from './SendTestEmailModal'

const LOGIC_PROPS = { id: 'new' }

const SANDBOX_SENDER = {
    id: 7,
    kind: 'email',
    display_name: 'Acme via PostHog <sandbox@example.com>',
    config: { provider: 'sandbox', name: 'Acme via PostHog', email: 'sandbox@example.com', verified: true },
    created_at: '2026-08-18T00:00:00Z',
}

const MEMBER_EMAIL = 'rose.dawson@posthog.com'

const SANDBOX_BLOCK_LOG = `Skipping send: the sandbox sender only sends to active organization members with verified email addresses. Blocked addresses: ${MEMBER_EMAIL}. Verify your own domain to send to anyone.`

type StoryArgs = {
    recipient?: string
    sendResult?: Record<string, unknown>
}

const meta: Meta<StoryArgs> = {
    title: 'Products/Workflows/Send test email modal',
    component: SendTestEmailModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER],
    },
}
export default meta

const Template: StoryFn<StoryArgs> = ({ recipient, sendResult }) => {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/integrations/': { results: [SANDBOX_SENDER] },
            '/api/environments/:team_id/messaging_templates/': { results: [] },
        },
        post: {
            '/api/projects/:team_id/integrations/email_sandbox_sender/': SANDBOX_SENDER,
            '/api/environments/:team_id/hog_flows/:id/invocations/': sendResult ?? { status: 'success' },
        },
    })
    const { setTemplateValue } = useActions(messageTemplateLogic(LOGIC_PROPS))
    const { setModalOpen, setRecipientEmail, sendTestEmail } = useActions(messageTemplateTestSendLogic(LOGIC_PROPS))

    useEffect(() => {
        setTemplateValue('content.email.subject', 'Welcome to Acme')
        setTemplateValue('content.email.text', 'Hello from the team.')
        setModalOpen(true)
        if (recipient) {
            setRecipientEmail(recipient)
        }
        if (sendResult) {
            sendTestEmail()
        }
    }, [recipient, sendResult, setTemplateValue, setModalOpen, setRecipientEmail, sendTestEmail])

    return <SendTestEmailModal {...LOGIC_PROPS} isOpen />
}

export const SandboxSenderPreselected: StoryFn<StoryArgs> = Template.bind({})
SandboxSenderPreselected.args = { recipient: MEMBER_EMAIL }

export const RecipientOutsideOrganization: StoryFn<StoryArgs> = Template.bind({})
RecipientOutsideOrganization.args = { recipient: 'outsider@example.com' }

export const SendBlockedByServer: StoryFn<StoryArgs> = Template.bind({})
SendBlockedByServer.args = {
    recipient: MEMBER_EMAIL,
    sendResult: { status: 'skipped', nextActionId: null, logs: [{ level: 'info', message: SANDBOX_BLOCK_LOG }] },
}
