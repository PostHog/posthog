import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { Button, Label, Switch } from '@posthog/quill'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { isSubscriptionEnabled, subscriptionEditHref } from './components/SubscriptionsTable'
import { deleteSubscriptionWithUndo } from './deleteSubscriptionWithUndo'
import { subscriptionSceneLogic } from './subscriptionSceneLogic'
import { SubscriptionTestDeliveryButton } from './SubscriptionTestDeliveryButton'

export function QuillSubscriptionDetailActions({ sub }: { sub: SubscriptionApi }): JSX.Element {
    const { push } = useActions(router)
    const { setEnabled } = useActions(subscriptionSceneLogic)
    const { subscriptionLoading } = useValues(subscriptionSceneLogic)
    const editHref = subscriptionEditHref(sub)
    const enabled = isSubscriptionEnabled(sub)

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
            <SubscriptionTestDeliveryButton sub={sub} />
            <Button
                variant="destructive-outline"
                data-attr="subscription-detail-delete"
                onClick={() => deleteSubscriptionWithUndo(sub)}
            >
                Delete
            </Button>
        </div>
    )
}
