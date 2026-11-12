import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { urls } from 'scenes/urls'

import { AddDeliveryWebhookModal } from './AddDeliveryWebhookModal'
import { DELIVERY_WEBHOOK_LIST_PROPS, deliveryWebhooksLogic } from './deliveryWebhooksLogic'

export function TransactionalWebhooks(): JSX.Element {
    const { engagementEventsEnabled, currentTeamLoading } = useValues(deliveryWebhooksLogic)
    const { openAddModal, enableEngagementEvents } = useActions(deliveryWebhooksLogic)

    return (
        <div className="flex flex-col gap-4">
            <p className="m-0 text-secondary">
                Get a signed request on your endpoint when a transactional email is sent, delivered, opened, clicked,
                bounced, marked as spam, or fails. Each request carries the message ID the send API returned.{' '}
                <code>data.template_id</code> and <code>data.template_key</code> hold the <code>template_id</code> or{' '}
                <code>template_key</code> your send passed. The one your send didn't pass is null. A key over 256
                characters is null in every request after the one for the sent email.
            </p>
            {!engagementEventsEnabled ? (
                <LemonBanner type="info">
                    <div className="flex flex-col gap-2">
                        <span>
                            Webhooks are sent from email engagement events, which are off for this project. Turn them on
                            to add a webhook. Engagement events count toward your event usage.
                        </span>
                        <div className="flex flex-wrap gap-2">
                            <LemonButton
                                type="primary"
                                size="small"
                                loading={currentTeamLoading}
                                onClick={enableEngagementEvents}
                                data-attr="transactional-webhook-enable-engagement-events"
                            >
                                Turn on engagement events
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={urls.settings('environment-workflows', 'workflows-engagement-events')}
                                targetBlank
                            >
                                Open settings
                            </LemonButton>
                        </div>
                    </div>
                </LemonBanner>
            ) : null}
            <HogFunctionList
                {...DELIVERY_WEBHOOK_LIST_PROPS}
                hideFeedback
                emptyText="No webhooks yet"
                returnTo={urls.transactional('webhooks')}
                extraControls={
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={openAddModal}
                        disabledReason={!engagementEventsEnabled ? 'Turn on engagement events first' : undefined}
                        data-attr="transactional-webhook-add"
                    >
                        Add webhook
                    </LemonButton>
                }
            />
            <AddDeliveryWebhookModal />
        </div>
    )
}
