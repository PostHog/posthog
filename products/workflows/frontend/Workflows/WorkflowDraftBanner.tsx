import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from './workflowLogic'

/**
 * A draft workflow never runs, but a passing test and an empty run list look the same as they do
 * for a live workflow with nothing to report. This names the draft state on the surfaces people
 * use to debug, and carries the enable action so they do not have to find it in the header.
 */
export function WorkflowDraftBanner({
    message,
    className,
}: {
    message: string
    className?: string
}): JSX.Element | null {
    const { originalWorkflow, hasUnsavedChanges, workflowUserAccessLevel } = useValues(workflowLogic)
    const { saveWorkflowPartial } = useActions(workflowLogic)

    if (originalWorkflow?.status !== 'draft') {
        return null
    }

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={workflowUserAccessLevel ?? undefined}
        >
            {({ disabledReason }) => (
                <LemonBanner
                    type="warning"
                    className={className}
                    action={{
                        children: 'Enable workflow',
                        'data-attr': 'workflow-draft-banner-enable',
                        onClick: () => saveWorkflowPartial({ status: 'active' }),
                        disabledReason: disabledReason ?? (hasUnsavedChanges ? 'Save your changes first' : undefined),
                    }}
                >
                    {message}
                </LemonBanner>
            )}
        </AccessControlAction>
    )
}
