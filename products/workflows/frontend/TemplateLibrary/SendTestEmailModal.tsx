import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { urls } from 'scenes/urls'

import { MessageTemplateLogicProps } from './messageTemplateLogic'
import { messageTemplateTestSendLogic } from './messageTemplateTestSendLogic'

export function SendTestEmailModal(props: MessageTemplateLogicProps & { isOpen: boolean }): JSX.Element {
    const { isOpen, ...logicProps } = props
    const logic = messageTemplateTestSendLogic(logicProps)
    const {
        recipientEmail,
        senderIntegrationId,
        emailIntegrations,
        integrationsLoading,
        sendDisabledReason,
        testSendResult,
        testSendResultLoading,
    } = useValues(logic)
    const { setModalOpen, setRecipientEmail, setSenderIntegrationId, sendTestEmail } = useActions(logic)

    return (
        <LemonModal
            title="Send test email"
            isOpen={isOpen}
            onClose={() => setModalOpen(false)}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => setModalOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        data-attr="send-test-email-submit"
                        loading={testSendResultLoading}
                        disabledReason={sendDisabledReason}
                        onClick={() => sendTestEmail()}
                    >
                        Send test email
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4 min-w-100">
                <div className="flex flex-col gap-1">
                    <LemonLabel>Send to</LemonLabel>
                    <LemonInput
                        type="email"
                        value={recipientEmail}
                        onChange={setRecipientEmail}
                        placeholder="you@example.com"
                        data-attr="send-test-email-recipient"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>From</LemonLabel>
                    {integrationsLoading && emailIntegrations.length === 0 ? (
                        <Spinner />
                    ) : emailIntegrations.length > 0 ? (
                        <LemonSelect
                            value={senderIntegrationId}
                            onChange={(id) => setSenderIntegrationId(id)}
                            options={emailIntegrations.map((integration) => ({
                                label: integration.display_name,
                                value: integration.id,
                            }))}
                            data-attr="send-test-email-sender"
                            fullWidth
                        />
                    ) : (
                        <div className="flex gap-2 items-center">
                            <span className="text-muted">No email senders configured yet</span>
                            <LemonButton
                                size="small"
                                type="secondary"
                                to={urls.workflows('channels')}
                                targetBlank
                                icon={<IconExternal />}
                            >
                                Connect email sender
                            </LemonButton>
                        </div>
                    )}
                </div>
                {testSendResult && testSendResult.status === 'skipped' ? (
                    <LemonBanner type="warning">
                        {testSendResult.logs?.map((log) => log.message).join(' ') ||
                            'The send was skipped for this recipient.'}
                    </LemonBanner>
                ) : testSendResult && testSendResult.status === 'error' ? (
                    <LemonBanner type="error">
                        {testSendResult.errors?.join(', ') || 'Failed to send test email'}
                    </LemonBanner>
                ) : null}
            </div>
        </LemonModal>
    )
}
