import { IconBrain } from '@posthog/icons'

import { inStorybookTestRunner } from 'lib/utils/dom'

import { TaskExecutionStatus as ExecutionStatus } from '~/queries/schema/schema-assistant-messages'

import { Activity } from '../components/ActivityPrimitives'
import { MarkdownMessage } from './MarkdownMessage'

export interface ReasoningAnswerProps {
    content: string
    completed: boolean
    id: string
    showCompletionIcon?: boolean
    animate?: boolean
}

export function ReasoningAnswer({
    content,
    completed,
    id,
    showCompletionIcon = true,
    animate = false,
}: ReasoningAnswerProps): JSX.Element {
    return (
        <Activity
            id={id}
            title={<MarkdownMessage id={id} content={completed ? 'Thought' : content} />}
            substeps={completed ? [content] : []}
            status={completed ? ExecutionStatus.Completed : ExecutionStatus.InProgress}
            icon={<IconBrain />}
            animate={!inStorybookTestRunner() && animate} // Avoiding flaky snapshots in Storybook
            showCompletionIcon={showCompletionIcon}
        />
    )
}
