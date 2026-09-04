import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { ProductKey } from '~/queries/schema/schema-general'

import { subscriptionsList } from '../generated/api'
import { subscriptionsSceneLogic } from '../scenes/subscriptionsSceneLogic'

/**
 * Setup detection for the subscriptions empty state. Subscriptions are a creation-first
 * product, so "set up" means the project has at least one, whatever it sends.
 */
export const subscriptionsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.SUBSCRIPTIONS,
    path: ['products', 'subscriptions', 'frontend', 'emptyState', 'subscriptionsSetupLogic'],
    detect: async () => {
        // limit=1 keeps the payload tiny; `count` reflects the full team total.
        const response = await subscriptionsList(String(getCurrentTeamId()), { limit: 1 })
        return (response.count ?? 0) > 0 ? 'has-data' : 'needs-setup'
    },
    // The empty state creates the first subscription in a modal, without leaving the scene,
    // so no remount would re-run detection and the gate would keep hiding what was created.
    recheckActionTypes: () => [subscriptionsSceneLogic.actionTypes.loadSubscriptionsSuccess],
})
