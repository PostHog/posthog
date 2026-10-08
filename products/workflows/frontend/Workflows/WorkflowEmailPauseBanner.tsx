import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from './workflowLogic'

export function WorkflowEmailPauseBanner(): JSX.Element | null {
    const {
        emailSendingPaused,
        emailSendingPausedReason,
        emailSendingPausedByStaff,
        emailSendingPauseRequiresSupport,
        resumeEmailSendingPending,
        hasUnsavedChanges,
        workflowUserAccessLevel,
    } = useValues(workflowLogic)
    const { resumeEmailSending } = useActions(workflowLogic)

    // The resume endpoint needs editor access, so a viewer gets a disabled button with the reason
    // instead of a confirm dialog that can only end in an error.
    const accessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor,
        workflowUserAccessLevel ?? undefined
    )

    if (!emailSendingPaused) {
        return null
    }

    if (emailSendingPauseRequiresSupport) {
        return (
            <LemonBanner type="error" data-attr="workflow-email-paused-banner">
                {emailSendingPausedByStaff
                    ? 'PostHog staff paused email sending for this workflow to protect delivery for everyone.'
                    : 'Email sending for this workflow was paused again soon after it was resumed.'}{' '}
                Its other steps still run. {emailSendingPausedReason} Remove old or bought addresses from the audience,
                then contact support to get sending re-enabled.
            </LemonBanner>
        )
    }

    return (
        <LemonBanner
            type="error"
            data-attr="workflow-email-paused-banner"
            action={{
                children: 'Resume sending',
                onClick: resumeEmailSending,
                // LemonButton disables itself while loading, so this is also the double-submit guard.
                loading: resumeEmailSendingPending,
                // Resuming reloads the workflow from the server, which resets the editor and would
                // drop whatever the form still holds.
                disabledReason: accessDisabledReason ?? (hasUnsavedChanges ? 'Save your changes first' : undefined),
                'data-attr': 'workflow-email-paused-resume',
            }}
        >
            Email sending is paused for this workflow. Its other steps still run, and the rest of your workflows keep
            sending. {emailSendingPausedReason} Remove old or bought addresses from the audience and stop sending to
            people who never open anything, then resume sending.
        </LemonBanner>
    )
}
