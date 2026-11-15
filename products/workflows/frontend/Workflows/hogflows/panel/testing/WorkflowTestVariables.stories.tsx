import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonLabel } from '@posthog/lemon-ui'

import { WorkflowTestVariables } from './WorkflowTestVariables'

const meta: Meta<typeof WorkflowTestVariables> = {
    title: 'Workflows/Testing/Variables',
    component: WorkflowTestVariables,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

export const TaskOutput: StoryObj<typeof WorkflowTestVariables> = {
    render: function Render() {
        const [value, setValue] = useState('{"task_output": {"summary": "A sample result", "score": 3}}')
        return (
            <div className="max-w-100 flex flex-col gap-1">
                <LemonLabel>Test variables</LemonLabel>
                <WorkflowTestVariables value={value} onChange={setValue} />
            </div>
        )
    },
}
