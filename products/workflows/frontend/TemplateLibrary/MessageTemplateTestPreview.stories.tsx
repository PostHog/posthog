import type { Meta, StoryObj } from '@storybook/react'

import { MessageTemplateTestPreview } from './MessageTemplateTestPreview'

const meta: Meta<typeof MessageTemplateTestPreview> = {
    title: 'Workflows/Testing/Email preview',
    component: MessageTemplateTestPreview,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

export const PlainText: StoryObj<typeof MessageTemplateTestPreview> = {
    args: { loading: false, email: { subject: 'Hello Alex', html: '', text: 'A sample result' } },
}

export const InvalidTemplate: StoryObj<typeof MessageTemplateTestPreview> = {
    args: {
        loading: false,
        email: {
            subject: '',
            html: '',
            text: '',
            error: 'Could not preview this template. Check its Liquid expressions.',
        },
    },
}
