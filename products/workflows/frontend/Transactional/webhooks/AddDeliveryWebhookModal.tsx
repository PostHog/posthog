import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonCheckbox, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { DELIVERY_WEBHOOK_EVENTS } from './deliveryWebhookPayload'
import { deliveryWebhooksLogic } from './deliveryWebhooksLogic'

export function AddDeliveryWebhookModal(): JSX.Element {
    const { isAddModalOpen, createdSecret, isWebhookFormSubmitting, webhookFormChanged } =
        useValues(deliveryWebhooksLogic)
    const { closeAddModal, submitWebhookForm } = useActions(deliveryWebhooksLogic)

    if (createdSecret) {
        return (
            <LemonModal
                isOpen={isAddModalOpen}
                onClose={closeAddModal}
                closable={false}
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
            onClose={closeAddModal}
            closable={!isWebhookFormSubmitting}
            hasUnsavedInput={webhookFormChanged}
            title="Add webhook"
            description="Send a request to your endpoint when a transactional email is sent, delivered, opened, clicked, bounced, marked as spam, or fails."
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
                    {({ value, onChange }) => (
                        <div
                            role="group"
                            aria-label="Events"
                            className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2"
                        >
                            {DELIVERY_WEBHOOK_EVENTS.map(({ event, label }) => (
                                <LemonCheckbox
                                    key={event}
                                    label={label}
                                    checked={value.includes(event)}
                                    onChange={(checked) =>
                                        onChange(
                                            checked
                                                ? DELIVERY_WEBHOOK_EVENTS.map((e) => e.event).filter(
                                                      (e) => e === event || value.includes(e)
                                                  )
                                                : value.filter((e: string) => e !== event)
                                        )
                                    }
                                />
                            ))}
                        </div>
                    )}
                </LemonField>
            </Form>
        </LemonModal>
    )
}
