import { TZLabel } from 'lib/components/TZLabel'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { RECORDINGS_BLOCK_CAUSE } from '../logics/replayRecordingsLogic'
import { disabledReasonDetail, FREE_CREDITS_STOPPING, limitReachedTooltip, stoppedByFreeCredits } from './scannerCopy'
import { type ScannerStatus, SWEEP_INTERVAL_MINUTES } from './scannerStatus'

function formatInterval(minutes: number): string {
    // The throttle factor is any integer, so only whole hours read better in hours.
    if (minutes < 60 || minutes % 60 !== 0) {
        return pluralize(minutes, 'minute')
    }
    return minutes === 60 ? 'hour' : pluralize(minutes / 60, 'hour')
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
            return stoppedByFreeCredits(status) ? FREE_CREDITS_STOPPING : limitReachedTooltip(status)
        case 'quota_exhausted':
            return `Your organization's Replay Vision credits are used up${resetsOn ? ` until ${resetsOn}` : ''}.`
        case 'filter_error':
            return `The filters can't run, so no new recordings are scanned. ${status.message}`
        case 'paused':
            return "Not checking for new recordings because the scanner can't scan right now, for example because its experiment isn't running. Checks resume within a few hours, or right away when you edit the scanner."
        case 'starting':
            return 'The first scan is running. Results usually appear within 15 minutes.'
        case 'delayed':
            return (
                <>
                    Last checked for new recordings <TZLabel time={status.lastCheckedAt} />. Checks resume on their own.
                    If this lasts, contact support.
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
