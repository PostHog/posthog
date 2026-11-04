import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconChevronDown, IconLogomark, IconNotebook } from '@posthog/icons'
import { Button, ButtonGroup, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillMenuItems } from 'scenes/session-recordings/playlist/QuillMenuItems'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

import type { ReplayScannerApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { BUILT_IN_SUMMARY_LABEL, isSummaryObservation } from '../utils/observation'
import { quotaUx } from '../utils/quotaProjection'
import { ScanBlock } from '../utils/scanEligibility'
import { visionDocsUrl } from './DocsLink'
import { useSummarizeBlockedReason } from './useSummarizeBlockedReason'

/** Runs whichever summarizer `resolveSummarizer` settles on, and lets the user pick another. */
export function QuillSummarizeButton({
    sessionId,
    scanBlock,
}: {
    sessionId: string
    scanBlock: ScanBlock | null
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
    // The menu rows are their own buttons, so without this a second summarizer can start mid-run and spend the quota again.
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
        ? 'Watching this recording. The summary appears in the Observations section when it is ready.'
        : defaultSummarizer
          ? `Runs your "${defaultSummarizer.name}" scanner on this recording.`
          : 'Writes a summary using a built-in prompt.'

    const menuItems: LemonMenuItems = [
        ...summarizerScanners.map((scanner) => ({
            key: scanner.id,
            label: scanner.name,
            active: scanner.id === defaultSummarizer?.id,
            disabledReason: scannerDisabledReason(scanner),
            onClick: () => summarizeWith(scanner.id, true),
            'data-attr': 'vision-summarize-pick-scanner',
        })),
        {
            key: 'built-in',
            label: (
                <span className="flex items-center justify-between gap-2 w-full">
                    <span className="truncate">{BUILT_IN_SUMMARY_LABEL}</span>
                    <span className="flex items-center gap-1.5 text-xs shrink-0 text-muted-foreground">
                        <IconLogomark className="text-base" />
                        Built in
                    </span>
                </span>
            ),
            tooltip: 'Uses a built-in prompt. Nothing is saved to your scanners, so there is nothing to open or edit.',
            active: !defaultSummarizer,
            disabledReason: builtInDisabledReason,
            onClick: () => summarizeWith(null, true),
            'data-attr': 'vision-summarize-pick-built-in',
        },
    ]
    const showMenu = summarizerScanners.length > 0 && dataProcessingAccepted

    const button = (
        <Button
            size="sm"
            variant={hasSummary ? 'outline' : 'primary'}
            loading={summarizePending}
            // The endpoint refuses without org AI approval, so ask for it here rather than toasting a 400.
            onClick={() => {
                posthog.capture('replay_vision_summarize_clicked', {
                    recording_id: sessionId,
                    summarizer: defaultSummarizer ? 'configured' : 'built-in',
                    consent_needed: !dataProcessingAccepted,
                })
                if (dataProcessingAccepted) {
                    summarize(true)
                } else {
                    setConsentRequested(true)
                }
            }}
            disabledReason={defaultSummarizer ? scannerDisabledReason(defaultSummarizer) : builtInDisabledReason}
            tooltip={
                quotaTooltip ?? (
                    <span className="block max-w-72">
                        <span className="block mb-1">Replay vision uses AI to watch recordings for you.</span>
                        <span className="block">{summarizerTooltip}</span>
                        <LinkPrimitive
                            to={`${visionDocsUrl()}?utm_medium=in-product&utm_campaign=summarize-explainer`}
                            target="_blank"
                            className="block mt-1 underline"
                        >
                            Read the docs
                        </LinkPrimitive>
                    </span>
                )
            }
            data-attr="vision-summarize-recording"
            data-ph-capture-attribute-summarizer={defaultSummarizer ? 'configured' : 'built-in'}
        >
            <IconNotebook />
            <span className="truncate">{dataProcessingAccepted ? label : 'Allow AI analysis and summarize'}</span>
        </Button>
    )

    // The dropdown is the only way to reach a second summarizer, so it appears once one exists.
    const group = showMenu ? (
        <ButtonGroup>
            {button}
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            size="icon-sm"
                            variant={hasSummary ? 'outline' : 'primary'}
                            aria-label="Choose a summarizer"
                            disabledReason={inFlightDisabledReason ?? undefined}
                            data-attr="vision-summarize-choose"
                        />
                    }
                >
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <QuillMenuItems items={menuItems} />
                </DropdownMenuContent>
            </DropdownMenu>
        </ButtonGroup>
    ) : (
        button
    )

    if (dataProcessingAccepted) {
        return group
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
                summarize(true)
            }}
            onDismiss={() => setConsentRequested(false)}
        >
            {group}
        </AIConsentPopoverWrapper>
    )
}
