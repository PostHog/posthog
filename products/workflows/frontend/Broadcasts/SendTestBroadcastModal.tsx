import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { broadcastTestSendLogic } from './broadcastTestSendLogic'

export function SendTestBroadcastModal(): JSX.Element {
    const {
        isModalOpen,
        recipientEmail,
        previewPerson,
        sendDisabledReason,
        testSendResult,
        testSendSkipReason,
        testSendPartialFailure,
        testSendResultLoading,
        channel,
        recipientDistinctId,
    } = useValues(broadcastTestSendLogic)
    const { setModalOpen, setRecipientEmail, setRecipientDistinctId, sendTestEmail } =
        useActions(broadcastTestSendLogic)
    const isPush = channel === 'push'

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={() => setModalOpen(false)}
            title={isPush ? 'Send a test notification' : 'Send a test email'}
            description={
                isPush
                    ? "Goes to this person's devices only. Nobody in the audience receives it."
                    : 'Goes to this address only. Nobody in the audience receives it.'
            }
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
                {isPush ? (
                    <div className="flex flex-col gap-1">
                        <LemonLabel info="Starts as your own PostHog user's distinct ID. Use the ID your app identifies you with.">
                            Send to distinct ID
                        </LemonLabel>
                        <LemonInput
                            value={recipientDistinctId}
                            onChange={setRecipientDistinctId}
                            autoFocus
                            data-attr="broadcast-test-push-recipient"
                        />
                    </div>
                ) : (
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
                )}

                <span className="text-muted text-xs">
                    {previewPerson
                        ? `Variables use ${previewPerson.displayName}'s values, matching the preview.`
                        : 'No one matches this audience yet, so variables send as blank text.'}
                </span>

                {testSendSkipReason ? (
                    <LemonBanner type="warning">{testSendSkipReason}</LemonBanner>
                ) : testSendPartialFailure ? (
                    <LemonBanner type="warning">
                        Some apps took the notification, but at least one failed: {testSendPartialFailure}
                    </LemonBanner>
                ) : testSendResult?.status === 'skipped' ? (
                    <LemonBanner type="warning">
                        {testSendResult.logs?.map((log) => log.message).join(' ') ||
                            `The ${isPush ? 'push' : 'email'} step was skipped, so nothing was sent.`}
                    </LemonBanner>
                ) : null}
                {testSendResult?.status === 'error' && (
                    <LemonBanner type="error">
                        {testSendResult.errors?.join(', ') ||
                            `Could not send the test ${isPush ? 'notification' : 'email'}.`}
                    </LemonBanner>
                )}
            </div>
        </LemonModal>
    )
}
