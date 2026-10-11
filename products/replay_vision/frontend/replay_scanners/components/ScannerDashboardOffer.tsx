import { useActions, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'

import { scannerDashboardLogic, scannerDashboardOfferDismissKey } from '../scannerDashboardLogic'

export function ScannerDashboardOffer({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { showDashboardOffer } = useValues(scannerDashboardLogic({ scannerId }))
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: scannerDashboardOfferDismissKey(scannerId) }))
    if (!showDashboardOffer || isDismissed) {
        return null
    }
    return <VisibleScannerDashboardOffer scannerId={scannerId} />
}

function VisibleScannerDashboardOffer({ scannerId }: { scannerId: string }): JSX.Element {
    const { createdDashboardIdLoading } = useValues(scannerDashboardLogic({ scannerId }))
    const { createDashboard, dashboardOfferShown, dismissDashboardOffer } = useActions(
        scannerDashboardLogic({ scannerId })
    )
    useOnMountEffect(dashboardOfferShown)

    return (
        <LemonBanner
            type="info"
            dismissKey={scannerDashboardOfferDismissKey(scannerId)}
            onClose={dismissDashboardOffer}
            action={{
                children: 'Create dashboard',
                onClick: createDashboard,
                loading: createdDashboardIdLoading,
                'data-attr': 'vision-scanner-dashboard-offer-create',
            }}
        >
            Track this scanner's findings on a dashboard.
        </LemonBanner>
    )
}
