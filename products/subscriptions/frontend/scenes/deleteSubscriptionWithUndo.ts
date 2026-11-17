import { router } from 'kea-router'

import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { urls } from 'scenes/urls'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { subscriptionName } from './components/SubscriptionsTable'
import { subscriptionsSceneLogic } from './subscriptionsSceneLogic'

/** Deletes the subscription a detail page shows, with an undo toast, then goes back to the list. */
export function deleteSubscriptionWithUndo(sub: SubscriptionApi): void {
    void deleteWithUndo({
        endpoint: `projects/${String(getCurrentTeamId())}/subscriptions`,
        object: {
            id: sub.id,
            name: subscriptionName(sub),
        },
        callback: () => {
            subscriptionsSceneLogic.findMounted()?.actions.deleteSubscriptionSuccess()
            router.actions.push(urls.subscriptions())
        },
    })
}
