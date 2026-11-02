import { useActions, useValues } from 'kea'

import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditsRange } from '../../utils/credits'
import { quotaBannerState } from '../../utils/quotaProjection'
import { replayScannerLogic } from '../replayScannerLogic'
import { ReplayScannerTab } from '../replayScannerSceneLogic'
import { scanDrought } from '../scanDrought'
import { limitReachedTooltip, stoppedByFreeCredits } from '../scannerCopy'
import { scannerEditUrl } from '../scannerEditorSceneLogic'
import { ScannerStatus, SWEEP_INTERVAL_MINUTES, scannerStatus, spendAgainstLimit } from '../scannerStatus'
import { ScannerStatusLabel } from './ScannerStatusLabel'

function formatInterval(minutes: number): string {
    // The throttle factor is any integer, so only whole hours read better in hours.
    if (minutes < 60 || minutes % 60 !== 0) {
        return pluralize(minutes, 'minute')
    }
    return minutes === 60 ? 'hour' : pluralize(minutes / 60, 'hour')
}

function statusDetail(status: ScannerStatus, resetsOn: string | null, periodEndsOn: string | null): React.ReactNode {
    switch (status.kind) {
        case 'off':
            return status.reason === 'no_sampling'
                ? 'Sampling is set to 0%, so no recordings are scanned.'
                : "This scanner doesn't scan new recordings."
        case 'limit_reached':
            return stoppedByFreeCredits(status)
                ? `Paused until your free credits reset${periodEndsOn ? ` on ${periodEndsOn}` : ''}. Recordings until then are skipped.`
                : limitReachedTooltip(status)
        case 'quota_exhausted':
            return `Your organization's Replay Vision credits are used up${resetsOn ? ` until ${resetsOn}` : ''}.`
        case 'filter_error':
            return `The filters can't run, so no new recordings are scanned. ${status.message}`
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
                    {formatInterval(status.intervalMinutes)} instead of every {formatInterval(SWEEP_INTERVAL_MINUTES)}.
                    Last checked <TZLabel time={status.lastCheckedAt} />.
                </>
            )
        case 'running':
            return (
                <>
                    Checks for new recordings every {formatInterval(status.intervalMinutes)}. Last checked{' '}
                    <TZLabel time={status.lastCheckedAt} />.
                </>
            )
    }
}

export function ScannerStatusStrip({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner, observationStatsApi, togglingEnabled, turningOffFreeOnly } = useValues(
        replayScannerLogic({ id: scannerId })
    )
    const { toggleEnabled, turnOffFreeOnly } = useActions(replayScannerLogic({ id: scannerId }))
    const { quota } = useValues(visionQuotaLogic)
    if (!scanner) {
        return null
    }
    const quotaState = quotaBannerState(quota)
    const status = scannerStatus(scanner, {
        quotaExhausted: quotaState.kind === 'exhausted',
        drought: scanDrought(scanner, observationStatsApi?.labels.version_markers ?? null, new Date()),
    })
    const periodEndsOn = quota ? dayjs.utc(quota.period_end).format('MMMM D') : null
    const detail = statusDetail(status, quotaState.kind ? quotaState.resetsOn : null, periodEndsOn)
    const pausedByFreeCredits = status.kind === 'limit_reached' && stoppedByFreeCredits(status)
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner.user_access_level)
    const spend = spendAgainstLimit(scanner, quota)

    return (
        // min-h-38 matches the empty scout card beside it, so the two line up when there is no report yet.
        <div
            className="@container border rounded bg-surface-primary p-4 flex flex-col gap-3 min-h-38"
            data-attr="vision-scanner-status-strip"
            data-status={status.kind}
        >
            <div className="flex items-center justify-between gap-2 border-b border-primary pb-2">
                <span className="text-sm font-medium">Scanner status</span>
                <LemonSwitch
                    checked={scanner.enabled}
                    onChange={() => toggleEnabled()}
                    loading={togglingEnabled}
                    disabledReason={editDisabledReason}
                    label="Enabled"
                    size="small"
                    data-attr="vision-scanner-toggle-enabled"
                    data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                    data-ph-capture-attribute-will-be-enabled={!scanner.enabled}
                />
            </div>
            <div className="grid grid-cols-1 @2xl:grid-cols-2 gap-x-8 gap-y-4 items-start">
                <div className="min-w-0 flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <ScannerStatusLabel status={status} className="text-sm font-semibold" />
                    </div>
                    <div className="text-xs text-muted pl-4">
                        {detail}
                        {pausedByFreeCredits && quotaState.kind === 'exhausted' && (
                            <span>
                                {' '}
                                Your organization's spend limit is used up too, so raise it in billing as well.
                            </span>
                        )}
                        {(status.kind === 'no_matches' || status.kind === 'filter_error') && (
                            <>
                                {' '}
                                <Link
                                    to={urls.replayVisionScannerTriggers(scannerId)}
                                    data-attr="vision-scanner-status-review-filters"
                                >
                                    {status.kind === 'filter_error' ? 'Edit filters' : 'Review filters'}
                                </Link>
                            </>
                        )}
                    </div>
                    {pausedByFreeCredits && (
                        <div className="pl-4 pt-1 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                            <span className="text-xs text-muted">
                                Turn it off to keep scanning now. Scans past your free credits are billed.
                            </span>
                            <LemonSwitch
                                checked
                                onChange={() =>
                                    LemonDialog.open({
                                        title: 'Turn off free credits only?',
                                        description:
                                            scanner.credit_limit != null
                                                ? `This scanner will keep scanning after your free credits run out. Scans past them are billed, up to its limit of ${scanner.credit_limit.toLocaleString('en-US')} credits a month.`
                                                : "This scanner will keep scanning after your free credits run out. Scans past them are billed, up to your organization's spend limit.",
                                        primaryButton: { children: 'Turn off', onClick: () => turnOffFreeOnly() },
                                        secondaryButton: { children: 'Cancel' },
                                    })
                                }
                                loading={turningOffFreeOnly}
                                disabledReason={editDisabledReason}
                                label="Free credits only"
                                size="small"
                                bordered
                                data-attr="vision-scanner-status-turn-off-free-only"
                                data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                            />
                        </div>
                    )}
                </div>
                <div className="min-w-0 flex flex-col gap-1">
                    <div className="flex items-center justify-between gap-2 text-sm">
                        <span className="font-semibold">
                            {spend?.freeCredits ? 'Free credits' : 'Spending limit for this scanner'}
                        </span>
                        {spend && <span className="text-xs text-muted tabular-nums">{spend.usedPct}%</span>}
                    </div>
                    {spend ? (
                        <>
                            <LemonProgress
                                percent={spend.usedPct}
                                strokeColor={scanner.limit_reached ? 'var(--danger)' : undefined}
                            />
                            <span className="text-xs text-muted tabular-nums">
                                {spend.freeCredits
                                    ? `${Math.min(spend.used, spend.limit).toLocaleString('en-US')} of ${spend.limit.toLocaleString('en-US')} free credits used`
                                    : `${formatCreditsRange(spend.used, spend.limit)} used this billing period`}
                            </span>
                        </>
                    ) : (
                        <span className="text-xs text-muted">
                            No limit set. This scanner keeps scanning until your organization's credits run out.{' '}
                            {!editDisabledReason && (
                                <Link
                                    to={scannerEditUrl(scannerId, ReplayScannerTab.Overview)}
                                    data-attr="vision-scanner-status-set-limit"
                                >
                                    Set a limit
                                </Link>
                            )}
                        </span>
                    )}
                </div>
            </div>
        </div>
    )
}
