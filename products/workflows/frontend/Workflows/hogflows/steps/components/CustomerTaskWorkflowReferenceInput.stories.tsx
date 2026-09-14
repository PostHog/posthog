import { Meta, StoryFn } from '@storybook/react'
import { useState } from 'react'

import { CyclotronJobInputType } from '~/types'

import { CustomerTaskWorkflowReferenceInput } from './CustomerTaskWorkflowReferenceInput'

const meta: Meta<typeof CustomerTaskWorkflowReferenceInput> = {
    title: 'Products/Workflows/Steps/Customer task reference input',
    component: CustomerTaskWorkflowReferenceInput,
    parameters: {
        mockDate: '2026-01-01',
        msw: {
            mocks: {
                get: {
                    '/api/projects/:project_id/accounts/': {
                        results: [{ id: '11111111-1111-4111-8111-111111111111', name: 'Example account' }],
                    },
                },
            },
        },
    },
}
export default meta

const Template: StoryFn<typeof CustomerTaskWorkflowReferenceInput> = (args) => {
    const [input, setInput] = useState<CyclotronJobInputType>(args.input)
    return (
        <div className="p-4 max-w-lg">
            <CustomerTaskWorkflowReferenceInput {...args} input={input} onChange={setInput} />
        </div>
    )
}

export const Account = Template.bind({})
Account.args = {
    schema: { key: 'account_id', type: 'string', label: 'Account' },
    input: { value: '{variables.account.id}', templating: 'hog' },
    projectId: 1,
    sampleGlobals: { variables: { account: { id: '11111111-1111-4111-8111-111111111111' } } },
}

export const Assignee = Template.bind({})
Assignee.args = {
    schema: { key: 'assigned_to_id', type: 'string', label: 'Assignee' },
    input: { value: '{variables.owner_id}', templating: 'hog' },
    projectId: 1,
    sampleGlobals: { variables: { owner_id: 1 } },
}
