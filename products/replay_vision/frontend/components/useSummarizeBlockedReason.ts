import { useValues } from 'kea'

import { AccessControlLevel } from '~/types'

import type { ReplayScannerApi } from '../generated/api.schemas'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { limitReachedTooltip } from '../replay_scanners/scannerCopy'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { quotaUx } from '../utils/quotaProjection'
import { ScanBlock } from '../utils/scanEligibility'

// Summarizing writes a scanner, named or minted, and reads the recording, and the scan gate refuses a recording for
// every summarizer alike. So the reason blocks the button and each menu row instead of spending an ineligible scan.
export function useSummarizeBlockedReason(
    scanBlock: ScanBlock | null
): (scanner?: ReplayScannerApi | null) => string | null | undefined {
    const { quota } = useValues(visionQuotaLogic)
    const { disabledReason: quotaDisabledReason } = quotaUx(quota)
    return (scanner) =>
        getReplayVisionEditDisabledReason((scanner?.user_access_level as AccessControlLevel | null) ?? undefined) ??
        // A scanner past its credit limit answers 402 on observe, so it is refused here. The built-in prompt has no limit.
        (scanner?.limit_reached ? limitReachedTooltip(scanner) : null) ??
        scanBlock?.reason ??
        quotaDisabledReason
}
