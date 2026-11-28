import { TZLabel } from 'lib/components/TZLabel'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { ScannerStatusReasonEnumApi } from '../generated/api.schemas'
import { RECORDINGS_BLOCK_CAUSE } from '../logics/replayRecordingsLogic'
import { disabledReasonDetail, FREE_CREDITS_STOPPED, LIMIT_REACHED_TOOLTIP } from './scannerCopy'
import { type ScannerStatus, SWEEP_INTERVAL_MINUTES } from './scannerStatus'

function formatInterval(minutes: number): string {
    // The throttle factor is any integer, so only whole hours read better in hours.
    if (minutes < 60 || minutes % 60 !== 0) {
        return pluralize(minutes, 'minute')
    }
    return minutes === 60 ? 'hour' : pluralize(minutes / 60, 'hour')
}

function pausedDetail(reason: ScannerStatusReasonEnumApi | null): string {
    switch (reason) {
        case 'experiment_not_running':
            return "This scanner is paused because its experiment isn't running. It starts again when the experiment does."
        case 'credit_limit':
            return 'This scanner is paused because it reached a credit limit. It checks again within a few hours, or right away when you edit it.'
        default:
            return 'This scanner is paused. It checks again within a few hours, or right away when you edit it.'
    }
}

export function scannerStatusDetail(status: ScannerStatus, resetsOn: string | null): React.ReactNode {
    switch (status.kind) {
        case 'off':
            return disabledReasonDetail(status.reason)
        case 'no_sampling':
            return 'Sampling is set to 0%, so no recordings are scanned.'
        case 'replay_off':
            return `${RECORDINGS_BLOCK_CAUSE['replay-off']}, so there are no recordings to scan.`
        case 'no_recordings':
            return `${RECORDINGS_BLOCK_CAUSE['no-recordings']}, so there is nothing to scan.`
        case 'limit_reached':
            return status.freeCredits ? FREE_CREDITS_STOPPED : LIMIT_REACHED_TOOLTIP
        case 'quota_exhausted':
            return `Your organization's Replay Vision credits are used up${resetsOn ? ` until ${resetsOn}` : ''}.`
        case 'filter_error':
            return `This scanner's filters have an error, so it isn't scanning new recordings. ${status.message}`
        case 'paused':
            return pausedDetail(status.reason)
        case 'starting':
            return 'The first scan is running. Results usually appear within 15 minutes.'
        case 'delayed':
            return (
                <>
                    This scanner is behind. It last checked for new recordings <TZLabel time={status.lastCheckedAt} />{' '}
                    and catches up on its own. If it stays delayed, contact support.
                </>
            )
        case 'no_matches':
            return `${
                status.drought.everScanned
                    ? 'Nothing has matched since the last configuration change.'
                    : 'Nothing has matched yet.'
            } The filters may match no recordings${
                status.drought.samplingRate < 1
                    ? `, or ${percentage(status.drought.samplingRate)} sampling skipped them`
                    : ''
            }.`
        case 'throttled':
            return (
                <>
                    Its filters read a lot of data, so it checks for new recordings every{' '}
                    {formatInterval(status.intervalMinutes)}. Last checked <TZLabel time={status.lastCheckedAt} />.
                </>
            )
        case 'running':
            return (
                <>
                    Checks for new recordings every {formatInterval(status.intervalMinutes)}.
                    {status.intervalMinutes > SWEEP_INTERVAL_MINUTES &&
                        " It hasn't found recordings recently, so it checks less often until it finds some."}{' '}
                    Last checked <TZLabel time={status.lastCheckedAt} />.
                </>
            )
    }
}
