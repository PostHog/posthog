import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { Button, Label, Switch } from '@posthog/quill'

import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { urls } from 'scenes/urls'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { isSubscriptionEnabled, subscriptionEditHref, subscriptionName } from './components/SubscriptionsTable'
import { subscriptionSceneLogic } from './subscriptionSceneLogic'
import { subscriptionsSceneLogic } from './subscriptionsSceneLogic'

export function QuillSubscriptionDetailActions({ sub }: { sub: SubscriptionApi }): JSX.Element {
    const { push } = useActions(router)
    const { setEnabled, deliverSubscription } = useActions(subscriptionSceneLogic)
    const { subscriptionLoading, deliveringSubscriptionId } = useValues(subscriptionSceneLogic)
    const editHref = subscriptionEditHref(sub)
    const enabled = isSubscriptionEnabled(sub)
    const isDelivering = deliveringSubscriptionId === sub.id

    const deleteSubscription = (): void => {
        const name = subscriptionName(sub)
        void deleteWithUndo({
            endpoint: `projects/${String(getCurrentTeamId())}/subscriptions`,
            object: {
                id: sub.id,
                name,
            },
            callback: () => {
                subscriptionsSceneLogic.findMounted()?.actions.deleteSubscriptionSuccess()
                push(urls.subscriptions())
            },
        })
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-2">
                <Switch
                    id="subscription-toggle-enabled"
                    checked={enabled}
                    onCheckedChange={(newEnabled) => setEnabled({ enabled: newEnabled })}
                    disabledReason={subscriptionLoading ? 'Updating subscription…' : undefined}
                    data-attr="subscription-toggle-enabled"
                />
                <Label htmlFor="subscription-toggle-enabled">{enabled ? 'Enabled' : 'Disabled'}</Label>
            </div>
            {editHref ? (
                <Button variant="outline" onClick={() => push(editHref)}>
                    Edit subscription
                </Button>
            ) : null}
            <Button
                variant="primary"
                onClick={() => deliverSubscription(sub.id)}
                loading={isDelivering}
                disabledReason={isDelivering ? 'Sending test delivery…' : null}
                data-attr="subscription-detail-header-test-delivery"
            >
                Test delivery
            </Button>
            <Button variant="destructive-outline" data-attr="subscription-detail-delete" onClick={deleteSubscription}>
                Delete
            </Button>
        </div>
    )
}
