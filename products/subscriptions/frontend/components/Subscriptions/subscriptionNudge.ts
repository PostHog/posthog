import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { SubscriptionBaseProps, urlForSubscription } from './utils'

export const SUBSCRIPTION_PREFILL_PARAMS = {
    param: 'prefill',
    nudge: 'nudge',
    viaParam: 'via',
    viaToast: 'toast',
    viaNotification: 'notification',
    viaExport: 'export',
} as const

export type SubscriptionNudgeVia =
    | typeof SUBSCRIPTION_PREFILL_PARAMS.viaToast
    | typeof SUBSCRIPTION_PREFILL_PARAMS.viaExport

export function openSubscriptionFromNudge(
    target: SubscriptionBaseProps,
    { toastId, via }: { toastId?: string; via: SubscriptionNudgeVia }
): void {
    // A toast whose only content is the nudge has nothing left to offer once it is followed, and
    // names itself here to be closed. One shared with an export passes no id: that toast still
    // carries the export's download, which dismissing would discard.
    if (toastId) {
        lemonToast.dismiss(toastId)
    }
    router.actions.push(urlForSubscription('new', target), {
        [SUBSCRIPTION_PREFILL_PARAMS.param]: SUBSCRIPTION_PREFILL_PARAMS.nudge,
        [SUBSCRIPTION_PREFILL_PARAMS.viaParam]: via,
    })
}
