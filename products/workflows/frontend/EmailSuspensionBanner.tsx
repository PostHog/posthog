import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'
import { Callout, CalloutIcon, ItemContent, ItemDescription } from '@posthog/quill-primitives'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { workflowsEmailSuspensionLogic } from './workflowsEmailSuspensionLogic'

export function EmailSuspensionBanner(): JSX.Element | null {
    const { emailSendingSuspended, emailSendingSuspensionReason } = useValues(workflowsEmailSuspensionLogic)
    const quill = useFeatureFlag('LEMON_UI_TO_QUILL')

    if (!emailSendingSuspended) {
        return null
    }

    const body = (
        <>
            Email sending is suspended for this project. Workflow and broadcast emails are not being delivered.
            {emailSendingSuspensionReason ? <> Reason: {emailSendingSuspensionReason}.</> : null} Contact support to get
            sending re-enabled.
        </>
    )

    if (quill) {
        return (
            <Callout tone="destructive" data-attr="workflows-email-suspended-banner">
                <CalloutIcon />
                <ItemContent>
                    <ItemDescription>{body}</ItemDescription>
                </ItemContent>
            </Callout>
        )
    }

    return (
        <LemonBanner type="error" data-attr="workflows-email-suspended-banner">
            {body}
        </LemonBanner>
    )
}
