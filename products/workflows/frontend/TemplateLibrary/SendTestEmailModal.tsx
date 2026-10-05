import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInputSelect,
    LemonLabel,
    LemonSelect,
    LemonTag,
    Spinner,
} from '@posthog/lemon-ui'

import { SANDBOX_EMAIL_SENDER_NOTE } from 'lib/integrations/utils'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

import { MessageTemplateLogicProps } from './messageTemplateLogic'
import { messageTemplateTestSendLogic } from './messageTemplateTestSendLogic'

function senderOption(
    integration: IntegrationType,
    sandboxEmailSender: IntegrationType | null
): {
    label: string
    value: number
    labelInMenu?: JSX.Element
} {
    const option = { label: integration.display_name, value: integration.id }
    if (integration.id !== sandboxEmailSender?.id) {
        return option
    }
    return {
        ...option,
        labelInMenu: (
            <span className="flex items-center gap-2">
                {integration.display_name}
                <LemonTag type="highlight">Sandbox</LemonTag>
            </span>
        ),
    }
}

export function SendTestEmailModal(props: MessageTemplateLogicProps & { isOpen: boolean }): JSX.Element {
    const { isOpen, ...logicProps } = props
    const logic = messageTemplateTestSendLogic(logicProps)
    const {
        recipientEmail,
        recipientSuggestions,
        recipientOutsideOrganization,
        senderIntegrationId,
        sandboxEmailSender,
        isSandboxSenderSelected,
        emailIntegrations,
        emailIntegrationsLoading,
        sendDisabledReason,
        testSendResult,
        testSendResultLoading,
        testSendSkipMessage,
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
                    <LemonInputSelect
                        mode="single"
                        allowCustomValues
                        value={recipientEmail ? [recipientEmail] : []}
                        onChange={(values) => setRecipientEmail(values[0] ?? '')}
                        options={recipientSuggestions.map((email) => ({ key: email, label: email }))}
                        placeholder="you@example.com"
                        data-attr="send-test-email-recipient"
                    />
                    {recipientOutsideOrganization && (
                        <LemonBanner
                            type="warning"
                            action={{
                                children: 'Add your own sender',
                                to: urls.workflows('channels'),
                                targetBlank: true,
                            }}
                        >
                            {recipientEmail} is not a member of your organization. The sandbox sender only delivers to
                            verified members. Pick a teammate, or add your own sender to email anyone.
                        </LemonBanner>
                    )}
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>From</LemonLabel>
                    {emailIntegrationsLoading && emailIntegrations.length === 0 ? (
                        <Spinner />
                    ) : emailIntegrations.length > 0 ? (
                        <>
                            <LemonSelect
                                value={senderIntegrationId}
                                onChange={(id) => setSenderIntegrationId(id)}
                                options={emailIntegrations.map((integration) =>
                                    senderOption(integration, sandboxEmailSender)
                                )}
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
                {testSendSkipMessage ? (
                    <LemonBanner type="warning">
                        <div className="font-semibold">This test email was not sent</div>
                        <div>{testSendSkipMessage}</div>
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
