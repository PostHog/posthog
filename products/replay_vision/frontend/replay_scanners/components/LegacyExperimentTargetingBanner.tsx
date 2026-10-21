import { combineUrl } from 'kea-router'
import posthog from 'posthog-js'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { urls } from 'scenes/urls'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { legacyTargetingUpgradeParams } from '../experimentTargeting'
import type { ReplayScanner } from '../types'

export function LegacyExperimentTargetingBanner({ scanner }: { scanner: ReplayScanner }): JSX.Element | null {
    const params = legacyTargetingUpgradeParams(scanner)
    if (!params) {
        return null
    }
    return <VisibleLegacyExperimentTargetingBanner scanner={scanner} params={params} />
}

function VisibleLegacyExperimentTargetingBanner({
    scanner,
    params,
}: {
    scanner: ReplayScanner
    params: Record<string, string>
}): JSX.Element {
    const eventProperties = { scanner_id: scanner.id, scanner_type: scanner.scanner_type, enabled: scanner.enabled }
    useOnMountEffect(() => {
        posthog.capture('replay_vision_legacy_targeting_banner_shown', eventProperties)
    })

    return (
        <LemonBanner
            type="warning"
            action={{
                children: 'Create experiment scanner',
                to: combineUrl(urls.replayVisionScannerDetails('new'), params).url,
                onClick: () => posthog.capture('replay_vision_legacy_targeting_upgrade_clicked', eventProperties),
                // Creating a scanner needs resource-level edit access, not this scanner's own level.
                disabledReason: getReplayVisionEditDisabledReason(),
                'data-attr': 'vision-legacy-targeting-upgrade',
            }}
        >
            We added experiment scanners, and they are now the only scanners that can watch an experiment. The
            experiment targeting on this scanner will stop working soon. To keep watching this experiment, create an
            experiment scanner with the same experiment and filters.
        </LemonBanner>
    )
}
