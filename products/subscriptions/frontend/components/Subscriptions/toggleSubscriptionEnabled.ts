import { openTakeOwnershipDialog, ownerUnavailableCause, ResourceOwner } from 'lib/components/openTakeOwnershipDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import {
    subscriptionsPartialUpdate,
    subscriptionsTakeOwnershipCreate,
} from 'products/subscriptions/frontend/generated/api'

export async function toggleSubscriptionEnabled(
    id: number,
    enabled: boolean,
    owner: ResourceOwner | null
): Promise<boolean> {
    try {
        await subscriptionsPartialUpdate(String(getCurrentTeamId()), id, { enabled })
        lemonToast.success(enabled ? 'Subscription enabled' : 'Subscription disabled')
        return true
    } catch (e: any) {
        const cause = enabled ? ownerUnavailableCause(e) : null
        if (cause) {
            return await openTakeOwnershipDialog({
                resourceLabel: 'subscription',
                resourceId: id,
                owner,
                cause,
                takeOwnership: async () => {
                    await subscriptionsTakeOwnershipCreate(String(getCurrentTeamId()), String(id))
                    lemonToast.success('Subscription enabled')
                },
            })
        }
        const detail = typeof e?.detail === 'string' ? e.detail : null
        lemonToast.error(detail ?? 'Could not update subscription')
        return false
    }
}
