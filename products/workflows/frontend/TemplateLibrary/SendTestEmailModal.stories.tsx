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

const MEMBER_EMAIL = 'teammate@example.com'

type StoryArgs = {
    recipient?: string
}

const meta: Meta<StoryArgs> = {
    title: 'Products/Workflows/Send test email modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER],
    },
}
export default meta

const Template: StoryFn<StoryArgs> = ({ recipient }) => {
    useStorybookMocks({
        get: {
            '/api/organizations/:organization_id/members/': {
                results: [{ id: 'sandbox-teammate', user: { id: 42, email: MEMBER_EMAIL, is_email_verified: true } }],
            },
            '/api/projects/:team_id/integrations/': { results: [SANDBOX_SENDER] },
            '/api/environments/:team_id/messaging_templates/': { results: [] },
        },
    })
    const { setTemplateValue } = useActions(messageTemplateLogic(LOGIC_PROPS))
    const { setModalOpen, setRecipientEmail } = useActions(messageTemplateTestSendLogic(LOGIC_PROPS))

    useEffect(() => {
        setTemplateValue('content.email.subject', 'Welcome to Acme')
        setTemplateValue('content.email.text', 'Hello from the team.')
        setModalOpen(true)
        if (recipient) {
            setRecipientEmail(recipient)
        }
    }, [recipient, setTemplateValue, setModalOpen, setRecipientEmail])

    return <SendTestEmailModal {...LOGIC_PROPS} isOpen />
}

export const SandboxSenderPreselected: StoryFn<StoryArgs> = Template.bind({})
SandboxSenderPreselected.args = { recipient: MEMBER_EMAIL }

export const RecipientOutsideOrganization: StoryFn<StoryArgs> = Template.bind({})
RecipientOutsideOrganization.args = { recipient: 'outsider@example.com' }
