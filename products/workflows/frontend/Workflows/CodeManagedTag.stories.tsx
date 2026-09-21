import { Meta, StoryFn } from '@storybook/react'

import { LemonButton } from '@posthog/lemon-ui'

import { CodeManagedTag } from './CodeManagedTag'
import { codeManagedReason } from './codeManagedWorkflow'
import type { HogFlow } from './hogflows/types'

const meta: Meta<typeof CodeManagedTag> = {
    title: 'Products/Workflows/Code managed tag',
    component: CodeManagedTag,
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
        source_ref: '9f2c1ab',
        ...overrides,
    } as HogFlow
}

export const Basic: StoryFn = () => <CodeManagedTag workflow={workflow()} />

// The three source columns stay null until a push writes them, so the tag has to read without them
export const WithoutARecordedSource: StoryFn = () => (
    <CodeManagedTag workflow={workflow({ source_repository: null, source_path: null, source_ref: null })} />
)

// What the scene header shows: the tag beside the title, and a save button that says why it cannot save
export const ReadOnlyControls: StoryFn = () => (
    <div className="flex items-center gap-2">
        <h3 className="mb-0">Welcome sequence</h3>
        <CodeManagedTag workflow={workflow()} />
        <LemonButton type="primary" size="small" disabledReason={codeManagedReason(workflow())}>
            Save
        </LemonButton>
    </div>
)
