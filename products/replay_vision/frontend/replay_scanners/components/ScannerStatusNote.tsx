import { LemonBanner } from '@posthog/lemon-ui'

import type { LemonBannerAction, LemonBannerProps } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { urls } from 'scenes/urls'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { stoppedByFreeCredits } from '../scannerCopy'
import { scannerEditUrl } from '../scannerEditorSceneLogic'
import { isOffForAReason, type ScannerStatus } from '../scannerStatus'
import { scannerStatusDetail } from '../scannerStatusDetail'
import type { ReplayScanner } from '../types'
import { useScannerSave } from '../useScannerSave'
import { type StatusTone, statusLabel } from './ScannerStatusLabel'

// Project-wide causes have their own banners, and a person's own turn-off and the first scan have the idle note.
const NOTE_KINDS: ReadonlySet<ScannerStatus['kind']> = new Set([
    'filter_error',
    'no_sampling',
    'limit_reached',
    'paused',
    'delayed',
    'no_matches',
])

const BANNER_TYPE: Record<StatusTone, LemonBannerProps['type']> = {
    danger: 'error',
    warning: 'warning',
    success: 'info',
    muted: 'info',
}

export function ScannerStatusNote({
    scanner,
    status,
    onSaved,
}: {
    scanner: Pick<ReplayScanner, 'id' | 'user_access_level' | 'credit_limit'>
    status: ScannerStatus
    onSaved: () => void
}): JSX.Element | null {
    const { turnOn, turnOffFreeOnly, saving } = useScannerSave(scanner.id, onSaved)

    if (!NOTE_KINDS.has(status.kind) && !isOffForAReason(status)) {
        return null
    }
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner.user_access_level)
    const freeCreditsOff = status.kind === 'off' && status.reason === 'free_credits_used'
    const { label, tone } = statusLabel(status)

    const confirmTurnOffFreeOnly = (): void => {
        LemonDialog.open({
            title: 'Turn off free credits only?',
            description:
                scanner.credit_limit != null
                    ? `This scanner will keep scanning after free credits run out. Scans past them are billed, up to its limit of ${scanner.credit_limit.toLocaleString('en-US')} credits a month.`
                    : "This scanner will keep scanning after free credits run out. Scans past them are billed, up to your organization's spend limit.",
            primaryButton: { children: 'Turn off', onClick: () => void turnOffFreeOnly() },
            secondaryButton: { children: 'Cancel' },
        })
    }
    // Turning on runs the paid-scanning, consent or take-over step the off reason needs first.
    const turnOnAction = (children: string): LemonBannerAction => ({
        children,
        onClick: () => void turnOn(),
        loading: saving,
        disabledReason: editDisabledReason,
        'data-attr': 'vision-scanner-status-turn-on',
    })
    const linkAction = (children: string, to: string, dataAttr: string): LemonBannerAction => ({
        children,
        to,
        disabledReason: editDisabledReason,
        'data-attr': dataAttr,
    })

    const action = ((): LemonBannerAction | undefined => {
        switch (status.kind) {
            case 'off':
                switch (status.reason) {
                    case 'free_credits_used':
                        return turnOnAction('Turn off free credits only')
                    case 'no_ai_consent':
                        return turnOnAction('Allow AI analysis')
                    case 'creator_lost_access':
                        return turnOnAction('Take over and turn on')
                    default:
                        // A deleted experiment can't come back, so there is nothing to turn on.
                        return undefined
                }
            case 'no_matches':
                return linkAction(
                    'Review filters',
                    urls.replayVisionScannerTriggers(scanner.id),
                    'vision-scanner-status-review-filters'
                )
            case 'filter_error':
                return linkAction(
                    'Edit filters',
                    urls.replayVisionScannerTriggers(scanner.id),
                    'vision-scanner-status-edit-filters'
                )
            case 'no_sampling':
                return linkAction(
                    'Edit sampling',
                    scannerEditUrl(scanner.id, null),
                    'vision-scanner-status-edit-sampling'
                )
            case 'limit_reached':
                return stoppedByFreeCredits(status)
                    ? {
                          children: 'Turn off free credits only',
                          onClick: confirmTurnOffFreeOnly,
                          loading: saving,
                          disabledReason: editDisabledReason,
                          'data-attr': 'vision-scanner-status-turn-off-free-only',
                      }
                    : linkAction('Raise limit', scannerEditUrl(scanner.id, null), 'vision-scanner-status-raise-limit')
            default:
                return undefined
        }
    })()

    return (
        // LemonBanner drops data attributes, so the wrapper carries them.
        <div data-attr="vision-scanner-status-note" data-status={status.kind}>
            <LemonBanner
                // Hitting a limit is spend control doing its job, so it warns rather than reads as a failure.
                type={status.kind === 'limit_reached' || freeCreditsOff ? 'warning' : BANNER_TYPE[tone]}
                action={action}
            >
                <p className="font-semibold m-0">{label}</p>
                <p className="m-0">
                    {freeCreditsOff ? (
                        'Your free credits ran out, so this scanner turned off. Turn off free credits only to keep scanning. Scans past free credits are billed.'
                    ) : (
                        <>
                            {status.kind === 'off' && 'This scanner turned off. '}
                            {scannerStatusDetail(status, null)}
                        </>
                    )}
                </p>
            </LemonBanner>
        </div>
    )
}
