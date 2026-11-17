import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { subscriptionSceneLogic } from './subscriptionSceneLogic'

export function SubscriptionTestDeliveryButton({ sub }: { sub: SubscriptionApi }): JSX.Element {
    const { deliverSubscription } = useActions(subscriptionSceneLogic)
    const { deliveringSubscriptionId } = useValues(subscriptionSceneLogic)
    const isDelivering = deliveringSubscriptionId === sub.id

    return (
        <Button
            variant="primary"
            onClick={() => deliverSubscription(sub.id)}
            loading={isDelivering}
            disabledReason={isDelivering ? 'Sending test delivery…' : null}
            data-attr="subscription-detail-header-test-delivery"
        >
            Test delivery
        </Button>
    )
}
