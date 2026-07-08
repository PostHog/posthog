import type { Meta, StoryObj } from '@storybook/react'

import type { PreviewInviteResultApi } from './generated/api.schemas'
import { InvitePreviewModal } from './UserInterview'

const meta: Meta<typeof InvitePreviewModal> = {
    title: 'Scenes-App/User Interviews/Invite Preview Modal',
    component: InvitePreviewModal,
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            waitForSelector: '.LemonModal',
            waitForLoadersToDisappear: false,
        },
    },
}
export default meta

type Story = StoryObj<typeof InvitePreviewModal>

const emailHtml = `<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; color: #2d2d2d; max-width: 560px; margin: 0 auto; padding: 24px;">
  <h1 style="font-size: 22px; margin-bottom: 24px;">Got 5 minutes to chat?</h1>
  <p>Hey Alex,</p>
  <p>We're researching <strong>creating insights with the MCP integration</strong> and your perspective would be really valuable. Got 5&ndash;10 minutes for a quick voice conversation?</p>
  <p>It's a casual call with an AI interviewer &mdash; not a sales call, just research. You can do it whenever's convenient in the next few days.</p>
  <p style="text-align: center; margin: 32px 0;">
    <a href="#" target="_blank" style="background: #1d4aff; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600;">Start the interview</a>
  </p>
  <p style="font-size: 12px; color: #888;">Or paste this link into your browser: <a href="#">https://us.posthog.com/interview/preview</a></p>
  <p>Thanks!<br />The PostHog team</p>
</body>
</html>`

const emailablePreview: PreviewInviteResultApi = {
    interviewee_identifier: 'alex@example.com',
    user_name: 'Alex',
    email: 'alex@example.com',
    subject: 'Got 5 minutes to talk about creating insights with the MCP integration?',
    html: emailHtml,
    interview_url: 'https://us.posthog.com/interview/preview',
    emailable: true,
    is_preview_link: true,
}

export const Emailable: Story = {
    args: {
        isOpen: true,
        onClose: () => {},
        preview: emailablePreview,
        loading: false,
    },
}

export const Loading: Story = {
    args: {
        isOpen: true,
        onClose: () => {},
        preview: null,
        loading: true,
    },
}

export const NoEmailAddress: Story = {
    args: {
        isOpen: true,
        onClose: () => {},
        preview: {
            ...emailablePreview,
            interviewee_identifier: 'distinct_id_abc123',
            user_name: 'distinct_id_abc123',
            email: null,
            emailable: false,
        },
        loading: false,
    },
}
