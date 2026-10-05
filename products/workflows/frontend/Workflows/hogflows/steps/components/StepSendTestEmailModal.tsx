import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { WorkflowLogicProps } from '../../../workflowLogic'
import { stepTestSendLogic } from './stepTestSendLogic'

export function StepSendTestEmailModal({ logicProps }: { logicProps: WorkflowLogicProps }): JSX.Element {
    const logic = stepTestSendLogic(logicProps)
    const {
        isModalOpen,
        recipientEmail,
        previewPersonName,
        sendDisabledReason,
        testSendResult,
        testSendSkipReason,
        testSendResultLoading,
    } = useValues(logic)
    const { closeModal, setRecipientEmail, sendTestEmail } = useActions(logic)

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            title="Send a test email"
            description="Goes to this address only. Nobody in the workflow receives it, and no other step runs."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={sendTestEmail}
                        loading={testSendResultLoading}
                        disabledReason={sendDisabledReason}
                        data-attr="workflow-step-send-test-email"
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
                        data-attr="workflow-step-test-email-recipient"
                    />
                </div>

                <span className="text-muted text-xs">
                    {previewPersonName
                        ? `Merge tags use ${previewPersonName}'s values, from the event loaded in the test panel.`
                        : 'No test event is loaded, so merge tags use example values.'}
                </span>

                {testSendSkipReason ? (
                    <LemonBanner type="warning">{testSendSkipReason}</LemonBanner>
                ) : testSendResult?.status === 'skipped' ? (
                    <LemonBanner type="warning">
                        {testSendResult.logs?.map((log) => log.message).join(' ') ||
                            'The email step was skipped, so nothing was sent.'}
                    </LemonBanner>
                ) : null}
                {testSendResult?.status === 'error' && (
                    <LemonBanner type="error">
                        {testSendResult.errors?.join(', ') || 'Could not send the test email.'}
                    </LemonBanner>
                )}
            </div>
        </LemonModal>
    )
}
