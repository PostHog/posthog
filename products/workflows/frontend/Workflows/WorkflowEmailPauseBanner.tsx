import { useActions, useValues } from 'kea'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { EmailSendingPausedBanner } from './EmailSendingPausedBanner'
import { workflowLogic } from './workflowLogic'

export function WorkflowEmailPauseBanner(): JSX.Element | null {
    const { emailSendingPause, resumeEmailSendingPending, hasUnsavedChanges, workflowUserAccessLevel } =
        useValues(workflowLogic)
    const { resumeEmailSending } = useActions(workflowLogic)

    // The resume endpoint needs editor access, so a viewer gets a disabled button with the reason
    // instead of a confirm dialog that can only end in an error.
    const accessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor,
        workflowUserAccessLevel ?? undefined
    )

    return (
        <EmailSendingPausedBanner
            pause={emailSendingPause}
            subject="workflow"
            effect="Its other steps still run, and the rest of your workflows keep sending."
            onResume={resumeEmailSending}
            resuming={resumeEmailSendingPending}
            // Resuming reloads the workflow from the server, which resets the editor and would
            // drop whatever the form still holds.
            resumeDisabledReason={accessDisabledReason ?? (hasUnsavedChanges ? 'Save your changes first' : undefined)}
        />
    )
}
