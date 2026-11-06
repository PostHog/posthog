import { Meta, StoryFn } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { ReadOnlyTemplatePreview } from './ReadOnlyTemplatePreview'

const meta: Meta<typeof ReadOnlyTemplatePreview> = {
    title: 'Products/Workflows/Template library/Read-only template preview',
    component: ReadOnlyTemplatePreview,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/integrations/': {
                    count: 1,
                    results: [
                        {
                            id: 5,
                            kind: 'email',
                            display_name: 'Hedgebox',
                            config: { email: 'hello@example.com', name: 'Hedgebox', reply_to: 'support@example.com' },
                        },
                    ],
                },
            },
        }),
    ],
}
export default meta

export const UploadedFromCode: StoryFn<typeof ReadOnlyTemplatePreview> = () => (
    <ReadOnlyTemplatePreview
        email={{
            subject: 'Welcome to Hedgebox, {{ variables.first_name }}',
            preheader: 'Your files are ready to share',
            html: '<div style="font-family: sans-serif; padding: 24px"><h1>Welcome, {{ variables.first_name }}</h1><p>Your Hedgebox account is ready.</p><a href="https://example.com/start">Get started</a></div>',
            text: 'Welcome, {{ variables.first_name }}\n\nYour Hedgebox account is ready.\n\nGet started: https://example.com/start',
            design: null,
            from: { integrationId: 5, email: 'welcome@example.com', name: 'Hedgebox team' },
            replyTo: 'help@example.com',
            to: '',
        }}
    />
)
