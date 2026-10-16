import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconChevronDown, IconInfo, IconLogomark, IconNotebook } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { LemonMenuItem, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { AccessControlLevel } from '~/types'

import type { ReplayScannerApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { limitReachedTooltip } from '../replay_scanners/scannerCopy'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { BUILT_IN_SUMMARY_LABEL, isSummaryObservation } from '../utils/observation'
import { quotaUx } from '../utils/quotaProjection'
import { ScanBlock, recordingScanBlock } from '../utils/scanEligibility'
import { visionDocsUrl } from './DocsLink'

export function SummarizeRecordingBar({
    extraActions,
}: {
    /** Recording actions the host places beside the summarize button. */
    extraActions?: React.ReactNode
}): JSX.Element | null {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { isNotFound, isRecordingDeleted } = useValues(sessionRecordingDataCoordinatorLogic(logicProps))

    if (!sessionRecordingId || isNotFound || isRecordingDeleted) {
        return null
    }
    return <SummarizeRecordingBarContent sessionId={sessionRecordingId} extraActions={extraActions} />
}

/**
 * Why a summary cannot run on this recording right now, whatever summarizer would run it.
 *
 * Both paths are scanner writes: an inline scan mints a scanner, and `observe` is a write action on
 * the scanner it runs. Each also exposes recording contents, so both need recording read as well. A
 * recording the scan-time gate would refuse is refused for every summarizer, so it blocks the button
 * and each menu row rather than spending a scan that comes back ineligible. Pass a scanner for the
 * object-level check, so one this user cannot edit is refused here rather than by a 403.
 *
 * The bar reads this too: a disabled button explains itself on hover only, which is why people kept
 * clicking one that could never run.
 */
function useSummarizeBlockedReason(
    scanBlock: ScanBlock | null
): (scanner?: ReplayScannerApi | null) => string | null | undefined {
    const { quota } = useValues(visionQuotaLogic)
    const { disabledReason: quotaDisabledReason } = quotaUx(quota)
    return (scanner) =>
        getReplayVisionEditDisabledReason((scanner?.user_access_level as AccessControlLevel | null) ?? undefined) ??
        // `observe` answers 402 for a scanner that has spent its own credit limit, so a capped one is
        // refused here rather than by a failed request. The built-in prompt has no per-scanner limit.
        (scanner?.limit_reached ? limitReachedTooltip(scanner) : null) ??
        scanBlock?.reason ??
        quotaDisabledReason
}

/** Runs whichever summarizer `resolveSummarizer` settles on, and lets the user pick another. */
function SummarizeButton({ sessionId, scanBlock }: { sessionId: string; scanBlock: ScanBlock | null }): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { summarizePending, defaultSummarizer, summarizerScanners, observations } = useValues(logic)
    const { summarize, summarizeWith } = useActions(logic)
    const hasSummary = observations.some((o) => isSummaryObservation(o) && o.status === 'succeeded')
    const { quota } = useValues(visionQuotaLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [consentRequested, setConsentRequested] = useState(false)
    const { tooltip: quotaTooltip } = quotaUx(quota)
    const blockedReason = useSummarizeBlockedReason(scanBlock)
    // `loading` only disables the button itself. The caret and the menu rows are their own buttons, so
    // without this a second summarizer is one click away mid-run, and it spends the quota again.
    const inFlightDisabledReason = summarizePending ? 'A summary is already running' : null
    const builtInDisabledReason = inFlightDisabledReason ?? blockedReason()
    const scannerDisabledReason = (scanner: ReplayScannerApi): string | null | undefined =>
        inFlightDisabledReason ?? blockedReason(scanner)
    // Nobody could tell which summarizer the button used, so it says so. While a scan is running the
    // label is the only thing that says the click landed: the summary takes minutes to arrive.
    const idleLabel = hasSummary
        ? 'Summarize again'
        : defaultSummarizer
          ? `Summarize with ${defaultSummarizer.name}`
          : 'Summarize this recording'
    const label = summarizePending ? 'Summarizing…' : idleLabel
    const summarizerTooltip = summarizePending
        ? 'Watching this recording. The summary appears in the Observations tab when it is ready.'
        : defaultSummarizer
          ? `Runs your "${defaultSummarizer.name}" scanner on this recording.`
          : 'Writes a summary using a built-in prompt.'

    const menuItems: LemonMenuItem[] = [
        ...summarizerScanners.map((scanner) => ({
            key: scanner.id,
            label: scanner.name,
            active: scanner.id === defaultSummarizer?.id,
            disabledReason: scannerDisabledReason(scanner),
            onClick: () => summarizeWith(scanner.id),
            'data-attr': 'vision-summarize-pick-scanner',
        })),
        {
            key: 'built-in',
            // Every other row is a scanner the team owns and can open. This one is PostHog's, so it
            // carries the logomark and says so, rather than reading as a scanner they cannot find.
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
            onClick: () => summarizeWith(null),
            'data-attr': 'vision-summarize-pick-built-in',
        },
    ]

    const button = (
        <LemonButton
            size="small"
            type={hasSummary ? 'tertiary' : 'secondary'}
            icon={<IconNotebook />}
            loading={summarizePending}
            // The endpoint refuses without org AI approval, so ask for it here rather than toasting a 400.
            onClick={() => {
                posthog.capture('replay_vision_summarize_clicked', {
                    // Repeat clicks are the point of this event, and `$session_id` cannot tell them
                    // apart from one click each on two recordings.
                    recording_id: sessionId,
                    summarizer: defaultSummarizer ? 'configured' : 'built-in',
                    consent_needed: !dataProcessingAccepted,
                })
                if (dataProcessingAccepted) {
                    summarize()
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
                summarize()
            }}
            onDismiss={() => setConsentRequested(false)}
        >
            {button}
        </AIConsentPopoverWrapper>
    )
}

/**
 * The bar sits on every standard replay player, so it reaches people who have never heard of Replay
 * vision and meet the summarize button with no idea what it is or what it will spend.
 */
function SummarizeExplainer(): JSX.Element {
    return (
        <Tooltip
            placement="bottom"
            // Base UI opens tooltips on hover only, which leaves this unreachable on a touch device.
            openOnClick
            title={
                <>
                    <p className="mb-1">Replay vision uses AI to watch recordings for you.</p>
                    <p className="mb-0">
                        Summarizing writes up what the user did in this session, so you can read it instead of watching
                        it.
                    </p>
                </>
            }
            docLink={`${visionDocsUrl()}?utm_medium=in-product&utm_campaign=summarize-explainer`}
        >
            <span className="inline-flex items-center text-muted" data-attr="vision-summarize-info">
                <IconInfo />
            </span>
        </Tooltip>
    )
}

function SummarizeRecordingBarContent({
    sessionId,
    extraActions,
}: {
    sessionId: string
    extraActions?: React.ReactNode
}): JSX.Element {
    const { defaultSummarizer } = useValues(observationsDockLogic({ sessionId }))
    const { sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const scanBlock = recordingScanBlock(sessionPlayerMetaData)
    const summarizeBlockedReason = useSummarizeBlockedReason(scanBlock)(defaultSummarizer)

    return (
        <div
            className="flex items-center gap-2 lg:gap-3 h-11 px-3 shrink-0 border-t bg-surface-primary"
            // Frozen: dashboards and selectors still find the bar under its old name.
            data-attr="vision-observations-dock"
        >
            <SummarizeButton sessionId={sessionId} scanBlock={scanBlock} />
            <SummarizeExplainer />
            {extraActions}
            {summarizeBlockedReason && (
                <Tooltip title={summarizeBlockedReason}>
                    <span className="ml-auto text-muted text-xs truncate" data-attr="vision-dock-skipped">
                        {scanBlock ? `Skipped: ${scanBlock.label.toLowerCase()}` : summarizeBlockedReason}
                    </span>
                </Tooltip>
            )}
        </div>
    )
}
