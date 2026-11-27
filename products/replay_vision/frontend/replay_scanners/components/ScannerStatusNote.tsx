import { useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import type { LemonBannerAction } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { visionScannersPartialUpdate } from '../../generated/api'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { quotaBannerState } from '../../utils/quotaProjection'
import { saveScannerEnabled } from '../saveScannerEnabled'
import { disabledReasonDetail, stoppedByFreeCredits } from '../scannerCopy'
import { scannerEditUrl } from '../scannerEditorSceneLogic'
import type { ScannerStatus } from '../scannerStatus'
import { scannerStatusDetail } from '../scannerStatusDetail'
import type { ReplayScanner } from '../types'
import { statusLabel } from './ScannerStatusLabel'

// Project-wide causes have their own banners, and a person's own turn-off and the first scan have the idle note.
const NOTE_KINDS: ReadonlySet<ScannerStatus['kind']> = new Set([
    'filter_error',
    'no_sampling',
    'limit_reached',
    'paused',
    'delayed',
    'no_matches',
])

export function isOffForAReason(status: ScannerStatus | undefined): boolean {
    return status?.kind === 'off' && !!status.reason && status.reason !== 'manual'
}

export function ScannerStatusNote({
    scanner,
    status,
    onSaved,
}: {
    scanner: ReplayScanner
    status: ScannerStatus
    onSaved: () => void
}): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const { quota } = useValues(visionQuotaLogic)
    const [saving, setSaving] = useState(false)

    const offForAReason = isOffForAReason(status)
    const freeCreditsOff = status.kind === 'off' && status.reason === 'free_credits_used'
    if (!NOTE_KINDS.has(status.kind) && !offForAReason) {
        return null
    }
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner.user_access_level)
    const quotaState = quotaBannerState(quota)
    const { label, tone } = statusLabel(status)

    const turnOffFreeOnly = (): void => {
        LemonDialog.open({
            title: freeCreditsOff ? 'Turn off free credits only and start scanning?' : 'Turn off free credits only?',
            description:
                scanner.credit_limit != null
                    ? `This scanner will keep scanning after free credits run out. Scans past them are billed, up to its limit of ${scanner.credit_limit.toLocaleString('en-US')} credits a month.`
                    : "This scanner will keep scanning after free credits run out. Scans past them are billed, up to your organization's spend limit.",
            primaryButton: {
                children: freeCreditsOff ? 'Turn off and scan' : 'Turn off',
                onClick: async () => {
                    if (!currentTeamId) {
                        return
                    }
                    setSaving(true)
                    try {
                        await visionScannersPartialUpdate(String(currentTeamId), scanner.id, {
                            free_only: false,
                            ...(freeCreditsOff && { enabled: true }),
                        })
                        onSaved()
                    } catch (error: any) {
                        lemonToast.error(
                            `Couldn't turn off free credits only${error?.detail ? `: ${error.detail}` : ''}. Try again from the scanner's settings.`
                        )
                    } finally {
                        setSaving(false)
                    }
                },
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    // Turning on runs the consent or take-over step the reason needs first.
    const turnOn = async (): Promise<void> => {
        if (!currentTeamId) {
            return
        }
        setSaving(true)
        try {
            if (await saveScannerEnabled(String(currentTeamId), scanner.id, true)) {
                onSaved()
            }
        } catch (error: any) {
            lemonToast.error(
                `Couldn't turn on the scanner${error?.detail ? `: ${error.detail}` : ''}. Try again from its settings.`
            )
        } finally {
            setSaving(false)
        }
    }
    const turnOnAction = (children: string): LemonBannerAction => ({
        children,
        onClick: () => void turnOn(),
        loading: saving,
        disabledReason: editDisabledReason,
        'data-attr': 'vision-scanner-status-turn-on',
    })

    const turnOffFreeOnlyAction: LemonBannerAction = {
        children: 'Turn off free credits only',
        onClick: turnOffFreeOnly,
        loading: saving,
        disabledReason: editDisabledReason,
        'data-attr': 'vision-scanner-status-turn-off-free-only',
    }
    const action = ((): LemonBannerAction | undefined => {
        switch (status.kind) {
            case 'off':
                switch (status.reason) {
                    case 'free_credits_used':
                        return turnOffFreeOnlyAction
                    case 'no_ai_consent':
                        return turnOnAction('Allow AI analysis')
                    case 'creator_lost_access':
                        return turnOnAction('Take over and turn on')
                    default:
                        // A deleted experiment can't come back, so there is nothing to turn on.
                        return undefined
                }
            case 'no_matches':
                return {
                    children: 'Review filters',
                    to: urls.replayVisionScannerTriggers(scanner.id),
                    disabledReason: editDisabledReason,
                    'data-attr': 'vision-scanner-status-review-filters',
                }
            case 'filter_error':
                return {
                    children: 'Edit filters',
                    to: urls.replayVisionScannerTriggers(scanner.id),
                    disabledReason: editDisabledReason,
                    'data-attr': 'vision-scanner-status-edit-filters',
                }
            case 'no_sampling':
                return {
                    children: 'Edit sampling',
                    to: scannerEditUrl(scanner.id, null),
                    disabledReason: editDisabledReason,
                    'data-attr': 'vision-scanner-status-edit-sampling',
                }
            case 'limit_reached':
                return stoppedByFreeCredits(status)
                    ? turnOffFreeOnlyAction
                    : {
                          children: 'Raise limit',
                          to: scannerEditUrl(scanner.id, null),
                          disabledReason: editDisabledReason,
                          'data-attr': 'vision-scanner-status-raise-limit',
                      }
            default:
                return undefined
        }
    })()

    return (
        // LemonBanner drops data attributes, so the wrapper carries them.
        <div data-attr="vision-scanner-status-note" data-status={status.kind}>
            <LemonBanner
                // Hitting a limit is spend control doing its job, so it warns rather than reads as a failure.
                type={
                    status.kind === 'limit_reached' || freeCreditsOff
                        ? 'warning'
                        : status.kind === 'off' && status.reason === 'experiment_deleted'
                          ? 'info'
                          : tone === 'danger'
                            ? 'error'
                            : tone === 'warning'
                              ? 'warning'
                              : 'info'
                }
                action={action}
            >
                <p className="font-semibold m-0">{label}</p>
                <p className="m-0">
                    {freeCreditsOff
                        ? 'Your free credits ran out, so this scanner turned off. Turn off free credits only to keep scanning. Scans past free credits are billed.'
                        : status.kind === 'off'
                          ? `This scanner turned off. ${disabledReasonDetail(status.reason)}`
                          : scannerStatusDetail(status, quotaState.kind ? quotaState.resetsOn : null)}
                </p>
            </LemonBanner>
        </div>
    )
}
