import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useRef, useState } from 'react'

import { IconChevronDown, IconInfo, IconLogomark, IconNotebook } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { LemonMenuItem, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { AccessControlLevel } from '~/types'

import type { ReplayScannerApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { LIMIT_REACHED_TOOLTIP } from '../replay_scanners/scannerCopy'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { BUILT_IN_SUMMARY_LABEL, dockObservations, isUnsuccessfulScan } from '../utils/observation'
import { quotaUx } from '../utils/quotaProjection'
import { ScanBlock, recordingScanBlock } from '../utils/scanEligibility'
import { VisionDocsLink, visionDocsUrl } from './DocsLink'
import { ObservationDockCard } from './ObservationCard'

const COLLAPSED_HEIGHT = 44
const DEFAULT_EXPANDED_HEIGHT = 480
const MIN_EXPANDED_HEIGHT = 120
const MAX_EXPANDED_HEIGHT = 800

export function ObservationsDock(): JSX.Element | null {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    // The dock is a sibling of the player frame, so it kept its summarize button on screen even when
    // the frame had swapped itself for the "Recording not found" or "deleted" screen — a control that
    // could never summarize a recording that is not there. There is nothing to scan, so drop the dock.
    const { isNotFound, isRecordingDeleted } = useValues(sessionRecordingDataCoordinatorLogic(logicProps))

    if (!sessionRecordingId || isNotFound || isRecordingDeleted) {
        return null
    }
    return <ObservationsDockContent sessionId={sessionRecordingId} />
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
        (scanner?.limit_reached ? LIMIT_REACHED_TOOLTIP : null) ??
        scanBlock?.reason ??
        quotaDisabledReason
}

/** Runs whichever summarizer `resolveSummarizer` settles on, and lets the user pick another. */
function SummarizeButton({ sessionId, scanBlock }: { sessionId: string; scanBlock: ScanBlock | null }): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { summarizePending, defaultSummarizer, summarizerScanners } = useValues(logic)
    const { summarize, summarizeWith } = useActions(logic)
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
    const idleLabel = defaultSummarizer ? `Summarize with ${defaultSummarizer.name}` : 'Summarize this recording'
    const label = summarizePending ? 'Summarizing…' : idleLabel
    const summarizerTooltip = summarizePending
        ? 'Watching this recording. The summary appears below when it is ready.'
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
            type="secondary"
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
 * The dock sits on every standard replay player, so it reaches people who have never heard of Replay
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

function ObservationsDockContent({ sessionId }: { sessionId: string }): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { observations, observationsLoading, dockOpen, retryingObservationIds, defaultSummarizer, summarizePending } =
        useValues(logic)
    const { setDockOpen, retryObservation } = useActions(logic)
    // sessionRecordingPlayerLogic is keyed by playerKey+sessionRecordingId; seek the exact mounted
    // player by its bound props rather than a propless default instance.
    const { logicProps, sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const seekToTime = (ms: number): void => {
        sessionRecordingPlayerLogic.findMounted(logicProps)?.actions.seekToTime(ms)
    }
    const scanBlock = recordingScanBlock(sessionPlayerMetaData)
    // Why the button the bar just rendered cannot run, whatever summarizer it points at. Shown as a
    // visible line so the reason no longer hides behind a hover, which is what left people clicking a
    // control that could never fire. A running summary is not a block, so it is left out.
    const blockedReason = useSummarizeBlockedReason(scanBlock)
    const summarizeBlockedReason = summarizePending ? null : blockedReason(defaultSummarizer)

    const dockRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        logicKey: 'vision-observations-dock',
        placement: 'top',
        containerRef: dockRef,
    }
    const { desiredSize, isResizeInProgress } = useValues(resizerLogic(resizerProps))

    const shown = dockObservations(observations)
    // Collapsed, the dock is one bar with a caret, so a scan that left no result would sit behind it
    // unseen. The count says there is something to open for; the card inside says which scan and why.
    const unsuccessfulCount = shown.filter(isUnsuccessfulScan).length
    const hasContent = shown.length > 0 || observationsLoading
    const expandedHeight = Math.max(
        MIN_EXPANDED_HEIGHT,
        Math.min(MAX_EXPANDED_HEIGHT, desiredSize ?? DEFAULT_EXPANDED_HEIGHT)
    )

    return (
        <div
            ref={dockRef}
            className={`relative border-t bg-surface-primary overflow-hidden flex flex-col ${
                isResizeInProgress ? '' : 'transition-[max-height] duration-300 ease-out'
            }`}
            style={{ maxHeight: dockOpen ? expandedHeight : COLLAPSED_HEIGHT }}
            data-attr="vision-observations-dock"
        >
            {dockOpen && <Resizer {...resizerProps} />}
            <div className="flex items-center gap-2 lg:gap-3 h-11 px-3 shrink-0">
                <SummarizeButton sessionId={sessionId} scanBlock={scanBlock} />
                <SummarizeExplainer />
                {summarizeBlockedReason &&
                    !hasContent && (
                        // Collapsed with nothing to expand, the disabled button's tooltip is the only place
                        // the reason is explained, so the bar says it outright. A scan-block has a short
                        // label to lead with; a quota or access block carries only its full sentence.
                        <Tooltip title={summarizeBlockedReason}>
                            <span className="ml-auto text-muted text-xs truncate" data-attr="vision-dock-skipped">
                                {scanBlock ? `Skipped: ${scanBlock.label.toLowerCase()}` : summarizeBlockedReason}
                            </span>
                        </Tooltip>
                    )}
                {hasContent && (
                    <div className="ml-auto flex items-center gap-2 min-w-0">
                        {!dockOpen && unsuccessfulCount > 0 && (
                            <span className="text-muted text-xs truncate" data-attr="vision-dock-no-result-count">
                                No result from {unsuccessfulCount} {unsuccessfulCount === 1 ? 'scan' : 'scans'}
                            </span>
                        )}
                        <LemonButton
                            size="small"
                            icon={<IconChevronDown className={dockOpen ? 'rotate-180' : ''} />}
                            onClick={() => setDockOpen(!dockOpen)}
                            tooltip={dockOpen ? 'Collapse' : 'Expand'}
                            aria-label={dockOpen ? 'Collapse summary' : 'Expand summary'}
                            data-attr="vision-dock-toggle"
                            // This click also sets the auto-expand preference, so which way it went is
                            // the signal for whether people keep summaries open by default.
                            data-ph-capture-attribute-dock-action={dockOpen ? 'collapse' : 'expand'}
                        />
                    </div>
                )}
            </div>
            {dockOpen && (
                <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-2">
                    {observationsLoading && shown.length === 0 ? (
                        <div className="flex items-center gap-2 text-muted py-4">
                            <Spinner /> Loading summaries…
                        </div>
                    ) : shown.length === 0 && scanBlock ? (
                        <div className="text-muted text-sm py-4">
                            Replay vision skipped this recording, so it has no summary. {scanBlock.reason}{' '}
                            <VisionDocsLink page="observations" dataAttr="vision-skipped-docs-link-dock">
                                Learn how observations work
                            </VisionDocsLink>
                        </div>
                    ) : shown.length === 0 ? (
                        <div className="text-muted text-sm py-4">
                            No summary yet. Summarize this recording to generate one.{' '}
                            <VisionDocsLink page="observations" dataAttr="vision-empty-docs-link-dock">
                                Learn how observations work
                            </VisionDocsLink>
                        </div>
                    ) : (
                        shown.map((observation) => (
                            <ObservationDockCard
                                key={observation.id}
                                observation={observation}
                                onSeek={seekToTime}
                                onRetry={() => retryObservation(observation.id)}
                                retrying={retryingObservationIds.includes(observation.id)}
                            />
                        ))
                    )}
                </div>
            )}
        </div>
    )
}
