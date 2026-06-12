import type { Meta, StoryObj } from '@storybook/react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { type EmailTemplateData, EmailTemplateView } from './index'

const meta: Meta = {
    title: 'MCP Apps/Email template',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

const sampleHtml = `<!DOCTYPE html>
<html>
  <body style="margin:0;font-family:Helvetica,Arial,sans-serif;background:#f7f8f9;">
    <table width="100%" cellpadding="0" cellspacing="0" style="padding:24px 0;">
      <tr><td align="center">
        <table width="480" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;">
          <tr><td style="background:#1d4aff;padding:24px;color:#fff;font-size:20px;font-weight:600;">Welcome to Hedgebox</td></tr>
          <tr><td style="padding:24px;color:#111;font-size:15px;line-height:1.5;">
            <p>Hi {{ person.properties.name }},</p>
            <p>Thanks for signing up. Your files are ready to sync across every device.</p>
            <p style="margin:24px 0;"><a href="https://hedgebox.net/start" style="background:#1d4aff;color:#fff;padding:12px 20px;border-radius:6px;text-decoration:none;">Get started</a></p>
            <p style="color:#666;font-size:13px;">— The Hedgebox team</p>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>`

const richTemplate: EmailTemplateData = {
    id: 'tmpl-1',
    name: 'Welcome email',
    description: 'Sent to new signups right after they create an account.',
    type: 'email',
    content: {
        templating: 'liquid',
        email: { subject: 'Welcome to Hedgebox!', text: 'Welcome to Hedgebox!', html: sampleHtml },
    },
    _posthogUrl: 'https://us.posthog.com/project/1/workflows/library/templates/tmpl-1',
}

const plainTextTemplate: EmailTemplateData = {
    id: 'tmpl-2',
    name: 'Password reset',
    type: 'email',
    content: {
        templating: 'liquid',
        email: { subject: 'Reset your password', text: 'Click the link to reset your password: {{ reset_url }}' },
    },
}

export const Rendered: Story = {
    render: () => <EmailTemplateView template={richTemplate} />,
    name: 'Rendered email',
}

export const PlainTextFallback: Story = {
    render: () => <EmailTemplateView template={plainTextTemplate} />,
    name: 'Plain-text fallback',
}
