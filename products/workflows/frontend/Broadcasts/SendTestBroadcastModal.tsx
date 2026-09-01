import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { broadcastTestSendLogic } from './broadcastTestSendLogic'

/**
 * Sends the broadcast to one address so the author can read it in a real inbox before the audience
 * does. The audience is untouched by this.
 */
export function SendTestBroadcastModal(): JSX.Element {
    const { isModalOpen, recipientEmail, previewPerson, sendDisabledReason, testSendResult, testSendResultLoading } =
        useValues(broadcastTestSendLogic)
    const { setModalOpen, setRecipientEmail, sendTestEmail } = useActions(broadcastTestSendLogic)

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={() => setModalOpen(false)}
            title="Send a test email"
            description="Goes to this address only. Nobody in the audience receives it."
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => setModalOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={sendTestEmail}
                        loading={testSendResultLoading}
                        disabledReason={sendDisabledReason}
                        data-attr="broadcast-send-test-email"
                    >
                        Send test
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3 max-w-160">
                <div className="flex flex-col gap-1">
                    <LemonLabel>Send to</LemonLabel>
                    <LemonInput
                        type="email"
                        value={recipientEmail}
                        onChange={setRecipientEmail}
                        placeholder="you@example.com"
                        autoFocus
                        data-attr="broadcast-test-email-recipient"
                    />
                </div>

                <span className="text-muted text-xs">
                    {previewPerson
                        ? `Variables use ${previewPerson.displayName}'s values, matching the preview.`
                        : 'No one matches this audience yet, so variables send as blank text.'}
                </span>

                {testSendResult?.status === 'skipped' && (
                    <LemonBanner type="warning">
                        {testSendResult.logs?.map((log) => log.message).join(' ') ||
                            'The email step was skipped, so nothing was sent.'}
                    </LemonBanner>
                )}
                {testSendResult?.status === 'error' && (
                    <LemonBanner type="error">
                        {testSendResult.errors?.join(', ') || 'Could not send the test email.'}
                    </LemonBanner>
                )}
            </div>
        </LemonModal>
    )
}
