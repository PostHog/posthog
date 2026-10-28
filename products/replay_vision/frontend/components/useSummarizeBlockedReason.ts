import { useValues } from 'kea'

import { AccessControlLevel } from '~/types'

import type { ReplayScannerApi } from '../generated/api.schemas'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { limitReachedTooltip } from '../replay_scanners/scannerCopy'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { quotaUx } from '../utils/quotaProjection'
import { ScanBlock } from '../utils/scanEligibility'

/**
 * Why a summary cannot run on this recording right now, whatever summarizer would run it.
 *
 * Both paths are scanner writes: an inline scan mints a scanner, and `observe` is a write action on
 * the scanner it runs. Each also exposes recording contents, so both need recording read as well. A
 * recording the scan-time gate would refuse is refused for every summarizer, so it blocks the button
 * and each menu row rather than spending a scan that comes back ineligible. Pass a scanner for the
 * object-level check, so one this user cannot edit is refused here rather than by a 403.
 *
 * The bar reads this too: a disabled button explains itself on hover only, which is why people kept
 * clicking one that could never run.
 */
export function useSummarizeBlockedReason(
    scanBlock: ScanBlock | null
): (scanner?: ReplayScannerApi | null) => string | null | undefined {
    const { quota } = useValues(visionQuotaLogic)
    const { disabledReason: quotaDisabledReason } = quotaUx(quota)
    return (scanner) =>
        getReplayVisionEditDisabledReason((scanner?.user_access_level as AccessControlLevel | null) ?? undefined) ??
        // `observe` answers 402 for a scanner that has spent its own credit limit, so a capped one is
        // refused here rather than by a failed request. The built-in prompt has no per-scanner limit.
        (scanner?.limit_reached ? limitReachedTooltip(scanner) : null) ??
        scanBlock?.reason ??
        quotaDisabledReason
}
