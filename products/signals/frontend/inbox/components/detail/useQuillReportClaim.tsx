import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { toast } from '@posthog/quill'

import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { isMac } from 'lib/utils/dom'
import { fullNameOrEmail } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import type { _UserApi } from 'products/signals/frontend/generated/api.schemas'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { ReportOwnerKind, claimKeyIntent, reportOwnerKind, reportOwnerLabel } from '../../utils/reportFacts'
import { QuillTakeOverReportDialog } from './QuillTakeOverReportDialog'

const IS_MAC = isMac()

function overlayOpen(): boolean {
    return !!document.querySelector('[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]')
}

export interface QuillReportClaim {
    ownerKind: ReportOwnerKind
    ownerLabel: string
    holder: _UserApi | null
    claimedAt: string | null
    canClaim: boolean
    canUnclaim: boolean
    canTakeOver: boolean
    saving: boolean
    claim: () => void
    unclaim: () => void
    takeOver: () => void
    dialog: JSX.Element | null
}

export function useQuillReportClaim(report: SignalReport): QuillReportClaim {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { reportClaimant, teammateClaimHolder, isReportClaimable, claimSaving } = useValues(logic)
    const { setReportClaimed } = useActions(logic)
    const { user } = useValues(userLogic)
    const [confirmingTakeOver, setConfirmingTakeOver] = useState(false)
    const claimRequested = useRef(false)

    const ownerKind = reportOwnerKind(report, user?.uuid ?? null)
    const canUnclaim = ownerKind === 'me'
    const canTakeOver = !!teammateClaimHolder
    const unclaim = (): void => setReportClaimed(false)
    const claim = (): void => {
        claimRequested.current = true
        setReportClaimed(true)
    }

    // The claim listener reports no result, so the toast waits for the report to show the user's claim.
    useEffect(() => {
        if (ownerKind === 'me' && claimRequested.current) {
            claimRequested.current = false
            toast.success({
                title: 'You claimed this report',
                action: { label: 'Undo', onClick: () => setReportClaimed(false) },
            })
        }
    }, [ownerKind, setReportClaimed])

    useKeyboardHotkeys(
        {
            u: {
                action: (event) => {
                    const intent = overlayOpen()
                        ? null
                        : claimKeyIntent(event, IS_MAC, { canClaim: isReportClaimable, canUnclaim })
                    if (intent) {
                        // The chord replaces the browser's own view-source shortcut while the user holds the claim.
                        event.preventDefault()
                        ;(intent === 'claim' ? claim : unclaim)()
                    }
                },
                willHandleEvent: true,
            },
        },
        [canUnclaim, isReportClaimable, claimSaving]
    )

    return {
        ownerKind,
        ownerLabel: reportOwnerLabel(ownerKind, reportClaimant ? fullNameOrEmail(reportClaimant) : null),
        holder: reportClaimant,
        claimedAt: report.assignee?.claimed_at ?? null,
        canClaim: isReportClaimable,
        canUnclaim,
        canTakeOver,
        saving: claimSaving,
        claim,
        unclaim,
        takeOver: () => setConfirmingTakeOver(true),
        dialog:
            confirmingTakeOver && teammateClaimHolder ? (
                <QuillTakeOverReportDialog
                    holder={teammateClaimHolder}
                    holderIsAgent={report.assignee?.kind === 'agent'}
                    onClose={(confirmed) => {
                        setConfirmingTakeOver(false)
                        captureInboxReportAction({
                            report,
                            actionType: 'claim_dialog',
                            surface: 'detail_pane',
                            extra: { claim_step: 'take_over', starts_run: false, confirmed },
                        })
                        if (confirmed) {
                            setReportClaimed(true, true, report.assignee)
                        }
                    }}
                />
            ) : null,
    }
}
