import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'

/**
 * Give a quota-blocked scan trigger a response the moment it's clicked. The trigger can't lean on
 * `disabledReason`: LemonButton renders that as `aria-disabled`, which turns a click into a silent
 * no-op and only reveals the reason on hover. So a click lands here instead and points the user at
 * the one place they can lift the block.
 */
export function notifyScanQuotaBlocked(reason: string): void {
    lemonToast.error(reason, {
        // Fixed id so rapid repeat clicks refresh one toast rather than stacking a pile.
        toastId: 'vision-scan-quota-blocked',
        button: {
            label: 'Manage billing limits',
            action: () => router.actions.push(urls.organizationBilling()),
        },
    })
}
