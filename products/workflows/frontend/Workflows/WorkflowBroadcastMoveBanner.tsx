import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner, LemonDialog } from '@posthog/lemon-ui'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { canMoveToBroadcasts, workflowBroadcastMoveLogic } from './workflowBroadcastMoveLogic'
import { workflowLogic } from './workflowLogic'

export function WorkflowBroadcastMoveBanner({ id }: { id: string }): JSX.Element | null {
    const { originalWorkflow, hasUnsavedChanges, workflowUserAccessLevel } = useValues(workflowLogic)
    const { moving } = useValues(workflowBroadcastMoveLogic({ id }))
    const { moveToBroadcasts } = useActions(workflowBroadcastMoveLogic({ id }))
    const show = canMoveToBroadcasts(originalWorkflow)
    const dismissKey = `workflow-broadcast-move-${id}`
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey }))

    useEffect(() => {
        if (show && !isDismissed) {
            posthog.capture('workflow broadcast move suggestion shown', { workflow_id: id })
        }
    }, [show, isDismissed, id])

    if (!show) {
        return null
    }

    const disabledReason =
        getAccessControlDisabledReason(
            AccessControlResourceType.Workflow,
            AccessControlLevel.Editor,
            workflowUserAccessLevel ?? undefined
        ) ?? (hasUnsavedChanges ? 'Save your changes first' : undefined)

    return (
        <div className="shrink-0" data-attr="workflow-broadcast-move-banner">
            <LemonBanner
                type="info"
                dismissKey={dismissKey}
                onClose={() => posthog.capture('workflow broadcast move suggestion dismissed', { workflow_id: id })}
                action={{
                    children: 'Move to broadcasts',
                    loading: moving,
                    disabledReason,
                    'data-attr': 'workflow-broadcast-move',
                    onClick: () =>
                        LemonDialog.open({
                            title: 'Move this workflow to broadcasts?',
                            description:
                                'It keeps its runs and metrics, opens in the broadcast editor and leaves the Workflows list. You can still open it in the workflow editor to add steps. This cannot be undone.',
                            primaryButton: {
                                children: 'Move to broadcasts',
                                type: 'primary',
                                'data-attr': 'workflow-broadcast-move-confirm',
                                onClick: () => {
                                    posthog.capture('workflow broadcast move clicked', { workflow_id: id })
                                    moveToBroadcasts()
                                },
                            },
                            secondaryButton: { children: 'Cancel' },
                        }),
                }}
            >
                This workflow sends one email to a batch audience, which is a broadcast. Move it to broadcasts to track
                its deliveries, opens and clicks in the broadcast overview.
            </LemonBanner>
        </div>
    )
}
