import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'

export function StepAgentTaskConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'agent_task' }>>
}): JSX.Element {
    const action = node.data
    const { prompt, title, repository, create_pr, max_wait_duration } = action.config

    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    const update = (config: Partial<Extract<HogFlowAction, { type: 'agent_task' }>['config']>): void => {
        partialSetWorkflowActionConfig(action.id, config)
    }

    return (
        <>
            <StepSchemaErrors />

            <p className="mb-0">Start a PostHog Code task and wait for it to finish before continuing.</p>

            <LemonLabel>Prompt</LemonLabel>
            <LemonTextArea
                value={prompt ?? ''}
                onChange={(value) => update({ prompt: value })}
                placeholder="Describe what the task should do. Use {{ variable }} to insert workflow variables."
                minRows={4}
            />

            <LemonLabel>Task title</LemonLabel>
            <LemonInput
                value={title ?? ''}
                onChange={(value) => update({ title: value })}
                placeholder="Optional, defaults to the step name"
            />

            <LemonLabel>Repository</LemonLabel>
            <LemonInput
                value={repository ?? ''}
                onChange={(value) => update({ repository: value })}
                placeholder="org/repo (optional, uses the project's default repository)"
            />

            <LemonCheckbox
                checked={create_pr ?? true}
                onChange={(checked) => update({ create_pr: checked })}
                label="Open a pull request when the task finishes"
            />

            <LemonLabel>Max time to wait</LemonLabel>
            <p className="mb-0 text-secondary">
                Continue down the timeout path if the task has not finished within this duration.
            </p>
            <HogFlowDuration value={max_wait_duration} onChange={(value) => update({ max_wait_duration: value })} />
        </>
    )
}
