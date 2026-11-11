import { useActions, useValues } from 'kea'
import { ReactNode, useRef } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { pluralize } from 'lib/utils/strings'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import type { EstimateResponseApi } from '../../generated/api.schemas'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCredits } from '../../utils/credits'
import { type QuickScannerLogicProps, REPLAY_VISION_UPSELL_SHOWN, quickScannerLogic } from '../quickScannerLogic'
import { ScannerSpendChoiceFields } from './ScannerSpendChoiceFields'

export interface QuickScannerPopoverProps {
    logicProps: QuickScannerLogicProps
    title: string
    /** Which recordings the scanner watches, such as "Sessions with this error". */
    recordingsLabel: string
    /** What AI writes for each recording. */
    output: ReactNode
    /** The trigger. It gets the toggle, or ignores it when something else opens the popover. */
    children: (trigger: { open: boolean; toggle: () => void }) => JSX.Element
}

/**
 * Creates a fully prefilled Replay vision scanner from another product's page, so the person stays
 * where they are. The prefill sets what the scanner watches and writes; the person only picks the spend.
 */
export function QuickScannerPopover({
    logicProps,
    title,
    recordingsLabel,
    output,
    children,
}: QuickScannerPopoverProps): JSX.Element {
    const logic = quickScannerLogic(logicProps)
    const { popoverOpen } = useValues(logic)
    const { setPopoverOpen } = useActions(logic)
    const referenceRef = useRef<HTMLSpanElement>(null)

    return (
        <Popover
            visible={popoverOpen}
            // Otherwise a press on the trigger closes the popover and the trigger's own toggle reopens it.
            onClickOutside={(event) => {
                if (!referenceRef.current?.contains(event.target as Node)) {
                    setPopoverOpen(false)
                }
            }}
            overlay={
                <QuickScannerPopoverContent
                    logicProps={logicProps}
                    title={title}
                    recordingsLabel={recordingsLabel}
                    output={output}
                />
            }
            placement="bottom-end"
            fallbackPlacements={['top-end']}
            showArrow
        >
            <span ref={referenceRef} className="inline-flex">
                {children({ open: popoverOpen, toggle: () => setPopoverOpen(!popoverOpen) })}
            </span>
        </Popover>
    )
}

/** Reports the trigger as shown once it is on screen, for a trigger that renders with its page. */
export function QuickScannerTriggerShown({
    entryPoint,
    children,
}: {
    entryPoint: string
    children: JSX.Element
}): JSX.Element {
    return (
        <PostHogCaptureOnViewed name={REPLAY_VISION_UPSELL_SHOWN} properties={{ placement: entryPoint }}>
            {children}
        </PostHogCaptureOnViewed>
    )
}

export function QuickScannerPopoverContent({
    logicProps,
    title,
    recordingsLabel,
    output,
}: Omit<QuickScannerPopoverProps, 'children'>): JSX.Element {
    const logic = quickScannerLogic(logicProps)
    const {
        estimate,
        estimateLoading,
        spendChoice,
        freeCreditsLeft,
        budget,
        startDisabledReason,
        consentRequested,
        createdScanner,
        createdScannerLoading,
        createError,
    } = useValues(logic)
    const {
        setCreditCap,
        setBudget,
        startWatching,
        rememberConsentIntent,
        approveConsent,
        cancelConsent,
        setPopoverOpen,
        reportOpenScanner,
    } = useActions(logic)

    if (createdScanner) {
        return (
            <div className="flex flex-col gap-3 p-1 w-[24rem] max-w-full">
                <div className="flex items-center gap-1.5 font-semibold">
                    <IconSparkles className="text-ai" />
                    AI is watching new sessions
                </div>
                <div className="text-sm text-secondary">
                    A summary appears for each matching session after it ends. Find them in the scanner.
                </div>
                <div className="flex justify-end gap-2">
                    <LemonButton type="tertiary" size="small" onClick={() => setPopoverOpen(false)}>
                        Done
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        size="small"
                        to={urls.replayVision(createdScanner.id)}
                        targetBlank
                        onClick={reportOpenScanner}
                        data-attr={`${logicProps.entryPoint}-quick-scanner-open`}
                    >
                        Open scanner
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3 p-1 w-[24rem] max-w-full">
            <div className="flex flex-col gap-1">
                <div className="flex items-center gap-1.5 font-semibold">
                    <IconSparkles className="text-ai" />
                    {title}
                </div>
                <div className="text-xs text-secondary">
                    A Replay vision scanner watches new session recordings for you. Nothing runs until you click Start
                    watching.
                </div>
            </div>

            <div className="flex flex-col gap-1">
                <span className="text-sm font-semibold">Which recordings it watches</span>
                <span className="text-sm">{recordingsLabel}</span>
                <EstimateLine estimate={estimate} loading={estimateLoading} />
            </div>

            <div className="flex flex-col gap-1">
                <span className="text-sm font-semibold">What AI writes for each one</span>
                <div className="text-sm">{output}</div>
            </div>

            <ScannerSpendChoiceFields
                spendChoice={spendChoice}
                freeCreditsLeft={freeCreditsLeft}
                budget={budget}
                onCreditCapChange={setCreditCap}
                onBudgetChange={setBudget}
                dataAttrPrefix={`${logicProps.entryPoint}-quick-scanner`}
            />

            {createError ? <LemonBanner type="error">{createError}</LemonBanner> : null}

            <div className="flex justify-end">
                <AIConsentPopoverWrapper
                    placement="bottom-end"
                    showArrow
                    ignoreDismissal
                    hideTrainingDisclaimer
                    pendingRedirectUrl={window.location.pathname + window.location.search}
                    hidden={!consentRequested}
                    onBeforeApprove={rememberConsentIntent}
                    onApprove={approveConsent}
                    onDismiss={cancelConsent}
                >
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconSparkles />}
                        // Inside the consent popover's reference, so Lemon would add a dropdown chevron.
                        sideIcon={null}
                        loading={createdScannerLoading}
                        disabledReason={getReplayVisionEditDisabledReason() ?? startDisabledReason}
                        onClick={startWatching}
                        data-attr={`${logicProps.entryPoint}-quick-scanner-start`}
                    >
                        Start watching
                    </LemonButton>
                </AIConsentPopoverWrapper>
            </div>
        </div>
    )
}

function EstimateLine({
    estimate,
    loading,
}: {
    estimate: EstimateResponseApi | null
    loading: boolean
}): JSX.Element | null {
    if (loading) {
        return (
            <span className="flex items-center gap-1 text-xs text-secondary">
                <Spinner className="text-xs" /> Counting matching recordings
            </span>
        )
    }
    if (!estimate) {
        return null
    }
    if (estimate.matched_sessions_in_window === 0) {
        return (
            <span className="text-xs text-secondary">
                No recordings matched in the last {pluralize(estimate.window_days, 'day')}. AI watches new ones when
                they arrive.
            </span>
        )
    }
    return (
        <span className="text-xs text-secondary">
            {pluralize(estimate.matched_sessions_in_window, 'recording')} matched in the last{' '}
            {pluralize(estimate.window_days, 'day')}. About {formatCredits(estimate.estimated_credits_per_month)} a
            month.
        </span>
    )
}
