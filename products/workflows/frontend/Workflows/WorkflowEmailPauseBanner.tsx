import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from './workflowLogic'

// The scene is a full-height flex column, so without shrink-0 the editor squeezes the banner and its
// text runs over the tabs. LemonBanner drops unknown props, so the data-attr sits here too.
function PauseBannerFrame({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="shrink-0" data-attr="workflow-email-paused-banner">
            {children}
        </div>
    )
}

export function WorkflowEmailPauseBanner(): JSX.Element | null {
    const {
        emailSendingPaused,
        emailSendingPausedReason,
        emailSendingPausedByStaff,
        emailSendingPauseRequiresSupport,
        resumeEmailSendingPending,
        hasUnsavedChanges,
        workflowUserAccessLevel,
        workflow,
        originalWorkflow,
    } = useValues(workflowLogic)
    const { resumeEmailSending } = useActions(workflowLogic)
    const { openSupportForm } = useActions(supportLogic)

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
            <PauseBannerFrame>
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Contact support',
                        onClick: () =>
                            openSupportForm({
                                kind: 'support',
                                message: `Email sending is paused for the workflow "${originalWorkflow?.name || 'Unnamed workflow'}" (${workflow.id}), and only support can resume it. Please review it and re-enable sending. What I changed in its audience: `,
                            }),
                        'data-attr': 'workflow-email-paused-contact-support',
                    }}
                >
                    {emailSendingPausedByStaff
                        ? 'PostHog staff paused email sending for this workflow to protect delivery for everyone.'
                        : 'Email sending for this workflow was paused again soon after it was resumed.'}{' '}
                    Its other steps still run. {emailSendingPausedReason} Remove old or bought addresses from the
                    audience, then contact support to get sending re-enabled.
                </LemonBanner>
            </PauseBannerFrame>
        )
    }

    return (
        <PauseBannerFrame>
            <LemonBanner
                type="error"
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
                Email sending is paused for this workflow. Its other steps still run, and the rest of your workflows
                keep sending. {emailSendingPausedReason} Remove old or bought addresses from the audience and stop
                sending to people who never open anything, then resume sending.
            </LemonBanner>
        </PauseBannerFrame>
    )
}
