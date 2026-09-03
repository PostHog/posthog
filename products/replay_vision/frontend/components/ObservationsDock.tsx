import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconChevronDown, IconInfo, IconLogomark, IconNotebook } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { LemonMenuItem, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { AccessControlLevel } from '~/types'

import type { ReplayScannerApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { BUILT_IN_SUMMARY_LABEL, dockObservations, isUnsuccessfulScan } from '../utils/observation'
import { quotaUx } from '../utils/quotaProjection'
import { VisionDocsLink, visionDocsUrl } from './DocsLink'
import { ObservationDockCard } from './ObservationCard'

const COLLAPSED_HEIGHT = 44
const DEFAULT_EXPANDED_HEIGHT = 480
const MIN_EXPANDED_HEIGHT = 120
const MAX_EXPANDED_HEIGHT = 800

export function ObservationsDock(): JSX.Element | null {
    const { sessionRecordingId } = useValues(sessionRecordingPlayerLogic)

    if (!sessionRecordingId) {
        return null
    }
    return <ObservationsDockContent sessionId={sessionRecordingId} />
}

/** Runs whichever summarizer `resolveSummarizer` settles on, and lets the user pick another. */
function SummarizeButton({ sessionId }: { sessionId: string }): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { summarizing, defaultSummarizer, summarizerScanners } = useValues(logic)
    const { summarize, summarizeWith } = useActions(logic)
    const { quota } = useValues(visionQuotaLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [consentRequested, setConsentRequested] = useState(false)
    const { disabledReason: quotaDisabledReason, tooltip: quotaTooltip } = quotaUx(quota)
    // `loading` only disables the button itself. The caret and the menu rows are their own buttons, so
    // without this a second summarizer is one click away mid-run, and it spends the quota again.
    const inFlightDisabledReason = summarizing ? 'A summary is already running' : null
    // Both paths are scanner writes: an inline scan mints a scanner, and `observe` is a write action on
    // the scanner it runs. Each also exposes recording contents, so both need recording read as well.
    const builtInDisabledReason = inFlightDisabledReason ?? getReplayVisionEditDisabledReason() ?? quotaDisabledReason
    // Object-level, so a scanner this user cannot edit is disabled rather than answering with a 403.
    const scannerDisabledReason = (scanner: ReplayScannerApi): string | null | undefined =>
        inFlightDisabledReason ??
        getReplayVisionEditDisabledReason(scanner.user_access_level as AccessControlLevel | null) ??
        quotaDisabledReason
    // Nobody could tell which summarizer the button used, so it says so.
    const label = defaultSummarizer ? `Summarize with ${defaultSummarizer.name}` : 'Summarize this recording'
    const summarizerTooltip = defaultSummarizer
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
            loading={summarizing}
            // The endpoint refuses without org AI approval, so ask for it here rather than toasting a 400.
            onClick={() => (dataProcessingAccepted ? summarize() : setConsentRequested(true))}
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
    const { observations, observationsLoading, dockOpen, retryingObservationIds } = useValues(logic)
    const { setDockOpen, retryObservation } = useActions(logic)
    // sessionRecordingPlayerLogic is keyed by playerKey+sessionRecordingId; seek the exact mounted
    // player by its bound props rather than a propless default instance.
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const seekToTime = (ms: number): void => {
        sessionRecordingPlayerLogic.findMounted(logicProps)?.actions.seekToTime(ms)
    }

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
                <SummarizeButton sessionId={sessionId} />
                <SummarizeExplainer />
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
