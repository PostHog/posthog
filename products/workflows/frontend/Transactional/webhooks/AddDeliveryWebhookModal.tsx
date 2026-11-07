import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonCheckbox, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { DELIVERY_WEBHOOK_EVENTS } from './deliveryWebhookPayload'
import { deliveryWebhooksLogic } from './deliveryWebhooksLogic'

export function AddDeliveryWebhookModal(): JSX.Element {
    const {
        isAddModalOpen,
        createdSecret,
        webhookForm,
        isWebhookFormSubmitting,
        transactionalEmailOptions,
        transactionalEmailOptionsLoading,
    } = useValues(deliveryWebhooksLogic)
    const { closeAddModal, submitWebhookForm, setWebhookFormValue } = useActions(deliveryWebhooksLogic)

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
            description="Send a request to your endpoint when a transactional email is sent, delivered, opened, or fails."
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
                <LemonField
                    name="workflowIds"
                    label="Transactional emails"
                    help="Leave empty to get updates for every transactional email, including ones you add later."
                >
                    <LemonInputSelect
                        mode="multiple"
                        options={transactionalEmailOptions}
                        loading={transactionalEmailOptionsLoading}
                        // The select also shows this when a search matches nothing, so it is set only for an empty list.
                        emptyStateComponent={
                            !transactionalEmailOptionsLoading && transactionalEmailOptions.length === 0 ? (
                                <p className="text-secondary italic p-1 m-0">
                                    No transactional emails yet. This webhook gets updates for every one you add.
                                </p>
                            ) : undefined
                        }
                        placeholder="All transactional emails"
                        data-attr="transactional-webhook-emails"
                    />
                </LemonField>
                <LemonField name="events" label="Events">
                    <div className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2">
                        {DELIVERY_WEBHOOK_EVENTS.map(({ event, label }) => (
                            <LemonCheckbox
                                key={event}
                                label={label}
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
                    </div>
                </LemonField>
            </Form>
        </LemonModal>
    )
}
