import { useActions, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'

import { formatCreditCount } from '../../utils/credits'
import { replayScannerLogic } from '../replayScannerLogic'
import { scannerRunTabLogic } from '../scannerRunTabLogic'

// pinned: localStorage key prefix, renaming it shows the offer again to everyone who dismissed it
const dismissKey = (scannerId: string): string => `vision-scanner-schedule-offer-${scannerId}`

export function ScannerScheduleOffer({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { showScheduleOffer } = useValues(scannerRunTabLogic({ scannerId }))
    // Checked out here so a dismissed banner never mounts and never counts as shown.
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: dismissKey(scannerId) }))
    if (!showScheduleOffer || isDismissed) {
        return null
    }
    return <VisibleScannerScheduleOffer scannerId={scannerId} />
}

function VisibleScannerScheduleOffer({ scannerId }: { scannerId: string }): JSX.Element {
    const { scannerEstimate, scannerEstimateLoading } = useValues(replayScannerLogic({ id: scannerId }))
    const { scheduleOfferShown, acceptScheduleOffer, dismissScheduleOffer } = useActions(
        scannerRunTabLogic({ scannerId })
    )
    useOnMountEffect(scheduleOfferShown)

    const monthlyCredits = scannerEstimate?.estimated_credits_per_month
    return (
        <LemonBanner
            type="info"
            dismissKey={dismissKey(scannerId)}
            onClose={dismissScheduleOffer}
            action={{
                children: 'Turn on schedule',
                onClick: acceptScheduleOffer,
                disabledReason: scannerEstimateLoading ? 'Estimating the monthly cost…' : undefined,
                'data-attr': 'vision-scanner-schedule-offer-accept',
            }}
        >
            This scanner only runs when you start a scan. Turn on its schedule to scan new matching recordings
            automatically
            {monthlyCredits != null ? `, about ${formatCreditCount(monthlyCredits)} a month.` : '.'}
        </LemonBanner>
    )
}
