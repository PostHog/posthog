import { Meta, StoryFn } from '@storybook/react'

import { CodeManagedSource } from './CodeManagedSource'
import { CodeManagedTag } from './CodeManagedTag'
import type { HogFlow } from './hogflows/types'

const meta: Meta<typeof CodeManagedSource> = {
    title: 'Products/Workflows/Code managed source',
    component: CodeManagedSource,
}
export default meta

function workflow(overrides: Partial<HogFlow> = {}): HogFlow {
    return {
        id: 'wf-1',
        name: 'Welcome sequence',
        description: '',
        team_id: 1,
        version: 3,
        status: 'active',
        exit_condition: 'exit_only_at_end',
        actions: [],
        edges: [],
        trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        managed_by: 'code',
        source_repository: 'github.com/example/flows',
        source_path: 'workflows/welcome.ts',
        source_ref: '9f2c1ab3d4e5f60718293a4b5c6d7e8f90a1b2c3',
        ...overrides,
    } as HogFlow
}

// The tag sits beside the title and the source line sits below it, so the stories render both.
const Template: StoryFn<{ workflow: HogFlow }> = ({ workflow }) => (
    <div className="flex flex-col gap-1 max-w-120">
        <div className="flex items-center gap-2">
            <h2 className="m-0">{workflow.name}</h2>
            <CodeManagedTag workflow={workflow} />
        </div>
        <CodeManagedSource workflow={workflow} />
    </div>
)

export const PushedFromACommit = Template.bind({})
PushedFromACommit.args = { workflow: workflow() }

export const PushedFromABranch = Template.bind({})
PushedFromABranch.args = { workflow: workflow({ source_ref: 'main' }) }

export const LongPathOnGitLab = Template.bind({})
LongPathOnGitLab.args = {
    workflow: workflow({
        source_repository: 'gitlab.com/example-group/marketing-automation-flows',
        source_path: 'workflows/lifecycle/onboarding/welcome-sequence-for-new-workspace-owners.ts',
    }),
}

// A host we cannot link reads as plain text rather than as a broken link
export const UnknownHost = Template.bind({})
UnknownHost.args = { workflow: workflow({ source_repository: 'git.example.com/team/flows' }) }

// The source columns stay null until a push writes them, so each part has to be optional
export const OnlyARepository = Template.bind({})
OnlyARepository.args = { workflow: workflow({ source_path: null, source_ref: null }) }
