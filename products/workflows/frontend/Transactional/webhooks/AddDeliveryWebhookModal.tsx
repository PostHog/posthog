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
        isWebhookFormSubmitting,
        webhookFormChanged,
        transactionalEmailOptions,
        transactionalEmailOptionsLoading,
        transactionalEmailOptionsError,
    } = useValues(deliveryWebhooksLogic)
    const { closeAddModal, submitWebhookForm, loadTransactionalEmailOptions } = useActions(deliveryWebhooksLogic)
    const noTransactionalEmailsYet =
        !transactionalEmailOptionsLoading && !transactionalEmailOptionsError && transactionalEmailOptions.length === 0

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
                <LemonField
                    name="workflowIds"
                    label="Transactional emails"
                    help="Leave empty to get updates for every transactional email, including ones you add later."
                >
                    <LemonInputSelect
                        mode="multiple"
                        options={transactionalEmailOptions}
                        loading={transactionalEmailOptionsLoading}
                        emptyStateComponent={
                            transactionalEmailOptionsError ? (
                                <p className="text-secondary italic p-1 m-0">
                                    Couldn't load your transactional emails.
                                </p>
                            ) : noTransactionalEmailsYet ? (
                                <p className="text-secondary italic p-1 m-0">
                                    No transactional emails yet. This webhook gets updates for every one you add.
                                </p>
                            ) : undefined
                        }
                        placeholder="All transactional emails"
                        data-attr="transactional-webhook-emails"
                    />
                </LemonField>
                {transactionalEmailOptionsError?.accessDenied ? (
                    <LemonBanner type="warning">
                        You don't have access to this project's email templates, so you can't pick emails here. Leave
                        the field empty to get updates for every transactional email.
                    </LemonBanner>
                ) : transactionalEmailOptionsError ? (
                    <LemonBanner
                        type="error"
                        action={{ children: 'Try again', onClick: () => loadTransactionalEmailOptions() }}
                    >
                        Couldn't load your transactional emails: {transactionalEmailOptionsError.message}. Try again, or
                        leave the field empty to get updates for all of them.
                    </LemonBanner>
                ) : null}
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
