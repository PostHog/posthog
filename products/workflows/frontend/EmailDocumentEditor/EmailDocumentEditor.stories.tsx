import { Meta, StoryFn } from '@storybook/react'
import { BindLogic } from 'kea'

import { emailTemplaterLogic, EmailTemplaterLogicProps } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { EmailDocumentEditor } from './EmailDocumentEditor'

const meta: Meta<typeof EmailDocumentEditor> = {
    title: 'Products/Workflows/Email document editor',
    component: EmailDocumentEditor,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
}
export default meta

const props: EmailTemplaterLogicProps = {
    type: 'native_email_template',
    value: { html: '', text: '', design: null, subject: '', from: '', to: '' },
    onChange: () => {},
    layout: 'inline',
}

export const Blank: StoryFn = () => (
    <BindLogic logic={emailTemplaterLogic} props={props}>
        <div className="flex flex-col h-screen">
            <EmailDocumentEditor />
        </div>
    </BindLogic>
)
