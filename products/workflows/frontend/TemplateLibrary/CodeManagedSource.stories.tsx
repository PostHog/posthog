import { Meta, StoryFn } from '@storybook/react'

import { CodeManagedSource } from './CodeManagedSource'
import { CodeManagedTag } from './CodeManagedTag'
import { templateSource } from './codeManagedTemplate'
import { NEW_TEMPLATE } from './constants'
import { MessageTemplate } from './types'

const meta: Meta<typeof CodeManagedSource> = {
    title: 'Products/Workflows/Template library/Code managed source',
    component: CodeManagedSource,
}
export default meta

function template(overrides: Partial<MessageTemplate> = {}): MessageTemplate {
    return {
        ...NEW_TEMPLATE,
        id: 'template-1',
        name: 'Welcome',
        key: 'welcome',
        managed_by: 'code',
        source_repository: 'github.com/example/app',
        source_path: 'emails/welcome.html',
        source_ref: '3f2c1ab9d4e5f60718293a4b5c6d7e8f90a1b2c3',
        ...overrides,
    }
}

const Template: StoryFn<{ template: MessageTemplate }> = ({ template }) => (
    <div className="flex flex-col gap-1 w-80">
        <div className="flex flex-wrap items-center gap-2">
            <h2 className="m-0">{template.name}</h2>
            <CodeManagedTag template={template} />
        </div>
        <CodeManagedSource source={templateSource(template)} />
    </div>
)

export const UploadedFromACommit = Template.bind({})
UploadedFromACommit.args = { template: template() }

export const LongPathOnGitLabBranch = Template.bind({})
LongPathOnGitLabBranch.args = {
    template: template({
        source_repository: 'gitlab.com/example/customer-lifecycle-emails',
        source_path: 'emails/onboarding/workspace-owners/welcome-to-your-new-workspace.html',
        source_ref: 'main',
    }),
}

export const UnknownHost = Template.bind({})
UnknownHost.args = { template: template({ source_repository: 'git.example.com/team/app' }) }

export const NoRecordedSource = Template.bind({})
NoRecordedSource.args = { template: template({ source_repository: null, source_path: null, source_ref: null }) }
