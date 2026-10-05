import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { getEmailSenderAddress } from 'scenes/hog-functions/email-templater/unverifiedEmailSenders'

import { IntegrationType } from '~/types'

import { EmailSetupModal } from '../Channels/EmailSetup/EmailSetupModal'
import { workflowLogic } from './workflowLogic'

export function WorkflowUnverifiedSenderBanner(): JSX.Element | null {
    const { unverifiedEmailSenders, originalWorkflow } = useValues(workflowLogic)
    const [senderToVerify, setSenderToVerify] = useState<IntegrationType | null>(null)
    const [firstSender] = unverifiedEmailSenders

    return (
        <>
            {firstSender && (
                <LemonBanner
                    type="warning"
                    data-attr="workflow-unverified-sender-banner"
                    action={{
                        children: 'Verify sender',
                        type: 'primary',
                        onClick: () => {
                            posthog.capture('workflows verify sender clicked', {
                                source: 'workflow_banner',
                                workflow_id: originalWorkflow?.id,
                            })
                            setSenderToVerify(firstSender)
                        },
                        'data-attr': 'workflow-verify-sender',
                    }}
                >
                    {unverifiedEmailSenders.length === 1
                        ? `Verify the email sender before you enable this workflow. ${getEmailSenderAddress(firstSender)} can't send until its domain is verified.`
                        : `Verify the email senders before you enable this workflow. ${unverifiedEmailSenders
                              .map(getEmailSenderAddress)
                              .join(', ')} can't send until their domains are verified.`}
                </LemonBanner>
            )}
            {/* Mounted outside the banner, so verifying the sender does not close the modal before the author sees the result. */}
            {senderToVerify && (
                <EmailSetupModal
                    integration={senderToVerify}
                    onComplete={() => setSenderToVerify(null)}
                    onClose={() => setSenderToVerify(null)}
                />
            )}
        </>
    )
}
