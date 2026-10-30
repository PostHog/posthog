import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconChevronDown, IconLogomark, IconNotebook } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenuItem, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import type { ReplayScannerApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { BUILT_IN_SUMMARY_LABEL, isSummaryObservation } from '../utils/observation'
import { quotaUx } from '../utils/quotaProjection'
import { ScanBlock } from '../utils/scanEligibility'
import { useSummarizeBlockedReason } from './useSummarizeBlockedReason'

/** Runs whichever summarizer `resolveSummarizer` settles on, and lets the user pick another. */
export function SummarizeButton({
    sessionId,
    scanBlock,
    inWatchLayout = false,
    fullWidth = false,
}: {
    sessionId: string
    scanBlock: ScanBlock | null
    inWatchLayout?: boolean
    fullWidth?: boolean
}): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { summarizePending, defaultSummarizer, summarizerScanners, observations } = useValues(logic)
    const { summarize, summarizeWith } = useActions(logic)
    const hasSummary = observations.some((o) => isSummaryObservation(o) && o.status === 'succeeded')
    const { quota } = useValues(visionQuotaLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [consentRequested, setConsentRequested] = useState(false)
    const { tooltip: quotaTooltip } = quotaUx(quota)
    const blockedReason = useSummarizeBlockedReason(scanBlock)
    // `loading` only disables this button. The caret and the menu rows are their own buttons, so without this a
    // second summarizer can start mid-run and spend the quota again.
    const inFlightDisabledReason = summarizePending ? 'A summary is already running' : null
    const builtInDisabledReason = inFlightDisabledReason ?? blockedReason()
    const scannerDisabledReason = (scanner: ReplayScannerApi): string | null | undefined =>
        inFlightDisabledReason ?? blockedReason(scanner)
    // While a scan runs the label is the only sign the click landed, because the summary takes minutes.
    const idleLabel = hasSummary
        ? 'Summarize again'
        : defaultSummarizer
          ? `Summarize with ${defaultSummarizer.name}`
          : 'Summarize this recording'
    const label = summarizePending ? 'Summarizing…' : idleLabel
    const summarizerTooltip = summarizePending
        ? `Watching this recording. The summary appears in the ${inWatchLayout ? 'Observations section' : 'Observations tab'} when it is ready.`
        : defaultSummarizer
          ? `Runs your "${defaultSummarizer.name}" scanner on this recording.`
          : 'Writes a summary using a built-in prompt.'

    const menuItems: LemonMenuItem[] = [
        ...summarizerScanners.map((scanner) => ({
            key: scanner.id,
            label: scanner.name,
            active: scanner.id === defaultSummarizer?.id,
            disabledReason: scannerDisabledReason(scanner),
            onClick: () => summarizeWith(scanner.id, inWatchLayout),
            'data-attr': 'vision-summarize-pick-scanner',
        })),
        {
            key: 'built-in',
            // This row is PostHog's built-in prompt, not a team scanner they could open, so it says so.
            label: (
                <span className="flex items-center justify-between gap-2 w-full">
                    <span className="truncate">{BUILT_IN_SUMMARY_LABEL}</span>
                    <span className="flex items-center gap-1.5 text-xs shrink-0">
                        <IconLogomark className="text-base text-primary" />
                        <span className="text-muted">Built in</span>
                    </span>
                </span>
            ),
            tooltip: 'Uses a built-in prompt. Nothing is saved to your scanners, so there is nothing to open or edit.',
            active: !defaultSummarizer,
            disabledReason: builtInDisabledReason,
            onClick: () => summarizeWith(null, inWatchLayout),
            'data-attr': 'vision-summarize-pick-built-in',
        },
    ]

    const button = (
        <LemonButton
            size="small"
            type={inWatchLayout ? (hasSummary ? 'secondary' : 'primary') : hasSummary ? 'tertiary' : 'secondary'}
            fullWidth={fullWidth}
            center={fullWidth}
            icon={<IconNotebook />}
            loading={summarizePending}
            // The endpoint refuses without org AI approval, so ask for it here rather than toasting a 400.
            onClick={() => {
                posthog.capture('replay_vision_summarize_clicked', {
                    // Repeat clicks on one recording are the point, and `$session_id` cannot tell them from one click each on two.
                    recording_id: sessionId,
                    summarizer: defaultSummarizer ? 'configured' : 'built-in',
                    consent_needed: !dataProcessingAccepted,
                })
                if (dataProcessingAccepted) {
                    summarize(inWatchLayout)
                } else {
                    setConsentRequested(true)
                }
            }}
            disabledReason={defaultSummarizer ? scannerDisabledReason(defaultSummarizer) : builtInDisabledReason}
            tooltip={quotaTooltip ?? summarizerTooltip}
            data-attr="vision-summarize-recording"
            data-ph-capture-attribute-summarizer={defaultSummarizer ? 'configured' : 'built-in'}
            // The dropdown is the only way to reach a second summarizer, so it appears once one exists.
            sideAction={
                summarizerScanners.length > 0 && dataProcessingAccepted
                    ? {
                          icon: <IconChevronDown />,
                          dropdown: { placement: 'bottom-end', overlay: <LemonMenuOverlay items={menuItems} /> },
                          divider: false,
                          disabledReason: inFlightDisabledReason,
                          'aria-label': 'Choose a summarizer',
                          'data-attr': 'vision-summarize-choose',
                      }
                    : null
            }
        >
            <span className="truncate">{dataProcessingAccepted ? label : 'Allow AI analysis and summarize'}</span>
        </LemonButton>
    )

    if (dataProcessingAccepted) {
        return button
    }

    return (
        <AIConsentPopoverWrapper
            placement="bottom-end"
            showArrow
            ignoreDismissal
            hideTrainingDisclaimer
            hidden={!consentRequested}
            onApprove={() => {
                setConsentRequested(false)
                summarize(inWatchLayout)
            }}
            onDismiss={() => setConsentRequested(false)}
        >
            {button}
        </AIConsentPopoverWrapper>
    )
}
