import { useActions } from 'kea'

import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { newWorkflowLogic } from './newWorkflowLogic'

export interface NewWorkflowButtonProps {
    size?: LemonButtonProps['size']
    className?: string
    onClick?: () => void
}

export function NewWorkflowButton({ size, className, onClick }: NewWorkflowButtonProps): JSX.Element {
    const { startNewWorkflow } = useActions(newWorkflowLogic)

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonButton
                type="primary"
                size={size}
                className={className}
                data-attr="new-workflow"
                onClick={() => {
                    onClick?.()
                    startNewWorkflow()
                }}
            >
                New workflow
            </LemonButton>
        </AccessControlAction>
    )
}
