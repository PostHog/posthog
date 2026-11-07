import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonLabel,
    LemonSelect,
    type LemonSelectOption,
    LemonTag,
    Spinner,
} from '@posthog/lemon-ui'

import { SANDBOX_EMAIL_SENDER_NOTE, isSandboxEmailSender } from 'lib/integrations/sandboxEmailSender'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

import { MessageTemplateLogicProps } from './messageTemplateLogic'
import { messageTemplateTestSendLogic } from './messageTemplateTestSendLogic'
import { TestEmailRecipientField } from './TestEmailRecipientField'

function senderOption(integration: IntegrationType): LemonSelectOption<number> {
    const option = { label: integration.display_name, value: integration.id }
    if (!isSandboxEmailSender(integration)) {
        return option
    }
    return {
        ...option,
        labelInMenu: (
            <span className="flex items-center gap-2">
                <span translate="no">{integration.display_name}</span>
                <LemonTag type="highlight">Sandbox</LemonTag>
            </span>
        ),
    }
}

export function SendTestEmailModal(props: MessageTemplateLogicProps & { isOpen: boolean }): JSX.Element {
    const { isOpen, ...logicProps } = props
    const logic = messageTemplateTestSendLogic(logicProps)
    const {
        senderIntegrationId,
        isSandboxSenderSelected,
        emailIntegrations,
        integrationsLoading,
        sendDisabledReason,
        testSendResult,
        testSendResultLoading,
        testSendSkipReason,
    } = useValues(logic)
    const { setModalOpen, setSenderIntegrationId, sendTestEmail } = useActions(logic)

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
                    <TestEmailRecipientField logicProps={logicProps} />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>From</LemonLabel>
                    {integrationsLoading && emailIntegrations.length === 0 ? (
                        <Spinner />
                    ) : emailIntegrations.length > 0 ? (
                        <>
                            <LemonSelect
                                value={senderIntegrationId}
                                onChange={(id) => setSenderIntegrationId(id)}
                                options={emailIntegrations.map(senderOption)}
                                data-attr="send-test-email-sender"
                                fullWidth
                            />
                            {isSandboxSenderSelected && (
                                <span className="text-xs text-secondary">{SANDBOX_EMAIL_SENDER_NOTE}</span>
                            )}
                        </>
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
                {testSendSkipReason ? (
                    <LemonBanner type="warning">{testSendSkipReason}</LemonBanner>
                ) : testSendResult && testSendResult.status === 'error' ? (
                    <LemonBanner type="error">
                        {testSendResult.errors?.join(', ') || 'Failed to send test email'}
                    </LemonBanner>
                ) : null}
            </div>
        </LemonModal>
    )
}
