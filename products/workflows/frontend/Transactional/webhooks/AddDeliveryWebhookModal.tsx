import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonCheckbox, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { DELIVERY_WEBHOOK_EVENTS, RECEIVED_EMAIL_EVENT } from './deliveryWebhookPayload'
import { deliveryWebhooksLogic } from './deliveryWebhooksLogic'

export function AddDeliveryWebhookModal(): JSX.Element {
    const { isAddModalOpen, createdSecret, webhookForm, isWebhookFormSubmitting, engagementEventsEnabled } =
        useValues(deliveryWebhooksLogic)
    const { closeAddModal, submitWebhookForm, setWebhookFormValue } = useActions(deliveryWebhooksLogic)
    const receivingEnabled = useFeatureFlag('WORKFLOWS_INBOUND_EMAIL')

    if (createdSecret) {
        return (
            <LemonModal
                isOpen={isAddModalOpen}
                onClose={closeAddModal}
                title="Webhook added"
                width={560}
                footer={
                    <LemonButton type="primary" onClick={closeAddModal} data-attr="transactional-webhook-secret-done">
                        Done
                    </LemonButton>
                }
            >
                <div className="flex flex-col gap-3">
                    <p className="m-0">
                        Each request is signed with this secret, following the Standard Webhooks spec. Use it to check
                        the <code>webhook-signature</code> header on your endpoint.
                    </p>
                    <LemonBanner type="warning">
                        Copy the secret now. You can't see it again after you close this.
                    </LemonBanner>
                    <div className="border rounded p-2 bg-surface-secondary break-all">
                        <CopyToClipboardInline description="signing secret" isValueSensitive selectable>
                            {createdSecret}
                        </CopyToClipboardInline>
                    </div>
                </div>
            </LemonModal>
        )
    }

    return (
        <LemonModal
            isOpen={isAddModalOpen}
            // Closing mid-request would hide the secret of a webhook the request still creates.
            onClose={isWebhookFormSubmitting ? undefined : closeAddModal}
            title="Add webhook"
            description={
                receivingEnabled
                    ? 'Send a request to your endpoint when a transactional email is sent, delivered, opened, or fails, or when an email is received.'
                    : 'Send a request to your endpoint when a transactional email is sent, delivered, opened, or fails.'
            }
            width={560}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeAddModal}
                        disabledReason={isWebhookFormSubmitting ? 'Adding the webhook' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitWebhookForm}
                        loading={isWebhookFormSubmitting}
                        data-attr="transactional-webhook-create"
                    >
                        Add webhook
                    </LemonButton>
                </>
            }
        >
            <Form logic={deliveryWebhooksLogic} formKey="webhookForm" className="flex flex-col gap-4">
                <LemonField name="url" label="Endpoint URL">
                    <LemonInput placeholder="https://example.com/webhooks/email" autoFocus />
                </LemonField>
                <LemonField name="events" label="Events">
                    <div className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2">
                        {DELIVERY_WEBHOOK_EVENTS.map(({ event, label }) => (
                            <LemonCheckbox
                                key={event}
                                label={label}
                                disabledReason={
                                    engagementEventsEnabled ? undefined : 'Turn on engagement events to use this event'
                                }
                                checked={webhookForm.events.includes(event)}
                                onChange={(checked) =>
                                    setWebhookFormValue(
                                        'events',
                                        checked
                                            ? DELIVERY_WEBHOOK_EVENTS.map((e) => e.event).filter(
                                                  (e) => e === event || webhookForm.events.includes(e)
                                              )
                                            : webhookForm.events.filter((e) => e !== event)
                                    )
                                }
                            />
                        ))}
                        {receivingEnabled && (
                            <LemonCheckbox
                                label="Received"
                                data-attr="transactional-webhook-received"
                                checked={webhookForm.events.includes(RECEIVED_EMAIL_EVENT)}
                                onChange={(checked) =>
                                    setWebhookFormValue(
                                        'events',
                                        checked
                                            ? [...webhookForm.events, RECEIVED_EMAIL_EVENT]
                                            : webhookForm.events.filter((e) => e !== RECEIVED_EMAIL_EVENT)
                                    )
                                }
                            />
                        )}
                    </div>
                </LemonField>
                {webhookForm.events.includes(RECEIVED_EMAIL_EVENT) && (
                    <LemonField
                        name="receivedRecipient"
                        label="Only for mail to"
                        info="Leave this empty to send every received email here. Otherwise, use part of an address, such as support@ or a domain."
                        showOptional
                    >
                        <LemonInput
                            placeholder="support@inbound.example.com"
                            data-attr="transactional-webhook-recipient"
                        />
                    </LemonField>
                )}
            </Form>
        </LemonModal>
    )
}
