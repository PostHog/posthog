import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { DistinctIdSelect } from 'lib/components/PropertyFilters/components/DistinctIdSelect'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { urls } from 'scenes/urls'

import { PropertyOperator } from '~/types'

import { WorkflowTestVariables } from '../Workflows/hogflows/panel/testing/WorkflowTestVariables'
import { MessageTemplateLogicProps } from './messageTemplateLogic'
import { MessageTemplateTestPreview } from './MessageTemplateTestPreview'
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
        testSendSkipReason,
        previewDistinctId,
        previewPersonLoading,
        variables,
        variablesError,
        previewEmail,
    } = useValues(logic)
    const {
        setModalOpen,
        setRecipientEmail,
        setSenderIntegrationId,
        sendTestEmail,
        setPreviewDistinctId,
        setVariables,
    } = useActions(logic)

    return (
        <LemonModal
            title="Send test email"
            width="40rem"
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
                <div className="flex flex-col gap-1">
                    <LemonLabel>Preview as person</LemonLabel>
                    <DistinctIdSelect
                        value={previewDistinctId}
                        operator={PropertyOperator.Exact}
                        forceSingleSelect
                        onChange={(value) => setPreviewDistinctId(typeof value === 'string' ? value : null)}
                    />
                    <span className="text-xs text-muted">
                        Uses this person's properties for the preview and test. The email is sent only to the address
                        above.
                    </span>
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Test variables</LemonLabel>
                    <WorkflowTestVariables value={variables} onChange={setVariables} />
                    {variablesError && <LemonBanner type="error">{variablesError}</LemonBanner>}
                </div>
                {!variablesError && <MessageTemplateTestPreview email={previewEmail} loading={previewPersonLoading} />}
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
