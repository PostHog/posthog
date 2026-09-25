import { useActions, useValues } from 'kea'

import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditsRange } from '../../utils/credits'
import { quotaBannerState } from '../../utils/quotaProjection'
import { replayScannerLogic } from '../replayScannerLogic'
import { scanDrought } from '../scanDrought'
import { LIMIT_REACHED_TOOLTIP } from '../scannerCopy'
import { ScannerStatus, SWEEP_INTERVAL_MINUTES, scannerStatus, spendAgainstLimit } from '../scannerStatus'

type StatusTone = 'success' | 'warning' | 'danger' | 'muted'

// Green and yellow mean the scanner is still sweeping, so their dot pulses. Tailwind's own pulse runs at 2s,
// which reads as urgent, so this slows it to 3s; reduced-motion users get a still dot.
const ACTIVE_PULSE = 'animate-[pulse_3s_cubic-bezier(0.4,0,0.6,1)_infinite] motion-reduce:animate-none'

const TONE_DOT: Record<StatusTone, string> = {
    success: 'bg-success',
    warning: 'bg-warning',
    danger: 'bg-danger',
    muted: 'bg-muted',
}

function formatInterval(minutes: number): string {
    // The throttle factor is any integer, so only whole hours read better in hours.
    if (minutes < 60 || minutes % 60 !== 0) {
        return pluralize(minutes, 'minute')
    }
    return minutes === 60 ? 'hour' : pluralize(minutes / 60, 'hour')
}

function statusCopy(
    status: ScannerStatus,
    resetsOn: string | null
): { label: string; tone: StatusTone; detail: React.ReactNode } {
    switch (status.kind) {
        case 'off':
            return {
                label: 'Off',
                tone: 'muted',
                detail:
                    status.reason === 'no_sampling'
                        ? 'Sampling is set to 0%, so no recordings are scanned.'
                        : "This scanner doesn't scan new recordings.",
            }
        case 'limit_reached':
            return { label: 'Stopped', tone: 'danger', detail: LIMIT_REACHED_TOOLTIP }
        case 'quota_exhausted':
            return {
                label: 'Stopped',
                tone: 'danger',
                detail: `Your organization's Replay Vision credits are used up${resetsOn ? ` until ${resetsOn}` : ''}.`,
            }
        case 'starting':
            return {
                label: 'Starting',
                tone: 'warning',
                detail: 'The first scan is running. Results usually appear within 15 minutes.',
            }
        case 'delayed':
            return {
                label: 'Delayed',
                tone: 'warning',
                detail: (
                    <>
                        Last checked for new recordings <TZLabel time={status.lastCheckedAt} />. Checks resume on their
                        own. If this lasts, contact support.
                    </>
                ),
            }
        case 'no_matches':
            return {
                label: 'No matches',
                tone: 'warning',
                detail: `${
                    status.drought.everScanned
                        ? 'Nothing has matched since the last configuration change.'
                        : 'Nothing has matched yet.'
                } The filters may match no recordings${
                    status.drought.samplingRate < 1
                        ? `, or ${percentage(status.drought.samplingRate)} sampling skipped them`
                        : ''
                }.`,
            }
        case 'throttled':
            return {
                label: 'Throttled',
                tone: 'warning',
                detail: (
                    <>
                        Its filters read a lot of data, so it checks for new recordings every{' '}
                        {formatInterval(status.intervalMinutes)} instead of every{' '}
                        {formatInterval(SWEEP_INTERVAL_MINUTES)}. Last checked <TZLabel time={status.lastCheckedAt} />.
                    </>
                ),
            }
        case 'running':
            return {
                label: 'Running',
                tone: 'success',
                detail: (
                    <>
                        Checks for new recordings every {formatInterval(status.intervalMinutes)}. Last checked{' '}
                        <TZLabel time={status.lastCheckedAt} />.
                    </>
                ),
            }
    }
}

export function ScannerStatusStrip({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner, observationStatsApi, togglingEnabled } = useValues(replayScannerLogic({ id: scannerId }))
    const { toggleEnabled } = useActions(replayScannerLogic({ id: scannerId }))
    const { quota } = useValues(visionQuotaLogic)
    if (!scanner) {
        return null
    }
    const quotaState = quotaBannerState(quota)
    const status = scannerStatus(scanner, {
        quotaExhausted: quotaState.kind === 'exhausted',
        drought: scanDrought(scanner, observationStatsApi?.labels.version_markers ?? null, new Date()),
    })
    const { label, tone, detail } = statusCopy(status, quotaState.kind ? quotaState.resetsOn : null)
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner.user_access_level)
    const spend = spendAgainstLimit(scanner)

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
                        <span
                            className={`size-2 rounded-full shrink-0 ${TONE_DOT[tone]} ${
                                tone === 'success' || tone === 'warning' ? ACTIVE_PULSE : ''
                            }`}
                            aria-hidden
                        />
                        <span className="text-sm font-semibold">{label}</span>
                    </div>
                    <div className="text-xs text-muted pl-4">
                        {detail}
                        {status.kind === 'no_matches' && (
                            <>
                                {' '}
                                <Link
                                    to={urls.replayVisionScannerTriggers(scannerId)}
                                    data-attr="vision-scanner-status-review-filters"
                                >
                                    Review filters
                                </Link>
                            </>
                        )}
                    </div>
                </div>
                <div className="min-w-0 flex flex-col gap-1">
                    <div className="flex items-center justify-between gap-2 text-sm">
                        <span className="font-semibold">Spending limit for this scanner</span>
                        {spend && <span className="text-xs text-muted tabular-nums">{spend.usedPct}%</span>}
                    </div>
                    {spend ? (
                        <>
                            <LemonProgress
                                percent={spend.usedPct}
                                strokeColor={scanner.limit_reached ? 'var(--danger)' : undefined}
                            />
                            <span className="text-xs text-muted tabular-nums">
                                {formatCreditsRange(spend.used, spend.limit)} used this billing period
                            </span>
                        </>
                    ) : (
                        <span className="text-xs text-muted">
                            No limit set. This scanner keeps scanning until your organization's credits run out.{' '}
                            {!editDisabledReason && (
                                <Link
                                    to={urls.replayVisionScannerConfigure(scannerId)}
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
