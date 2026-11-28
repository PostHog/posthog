import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'

import { VisualImageDiffViewer } from 'lib/components/VisualImageDiffViewer'
import { LemonBadge } from 'lib/lemon-ui/LemonBadge'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyMilliseconds } from 'lib/utils/durations'

import type { JourneyRunDetailApi, JourneyRunStepApi } from '../generated/api.schemas'
import { failureReasonLabel } from '../journeyRuns'
import { UserJourneyRunLogicProps, userJourneyRunLogic } from '../userJourneyRunLogic'
import { JourneyStepSummary } from './JourneyStepSummary'

const BADGE_STATUS = { passed: 'success', failed: 'danger', skipped: 'muted' } as const

export interface JourneyRunStepItemProps extends UserJourneyRunLogicProps {
    run: JourneyRunDetailApi
    step: JourneyRunStepApi
    isLast: boolean
}

export function JourneyRunStepItem({ id, runId, run, step, isLast }: JourneyRunStepItemProps): JSX.Element {
    const logic = userJourneyRunLogic({ id, runId })
    const { openStepIndexes, focusedStepIndex, comparisonMode } = useValues(logic)
    const { setStepOpen, setComparisonMode, screenshotFailedToLoad } = useActions(logic)
    const itemRef = useRef<HTMLLIElement>(null)

    const isFocused = focusedStepIndex === step.index
    const isOpen = openStepIndexes.has(step.index)
    const skipped = step.status === 'skipped'
    const hasScreenshot = step.screenshot_url !== null

    useEffect(() => {
        if (isFocused) {
            itemRef.current?.scrollIntoView({ block: 'nearest' })
        }
        // Only on mount: later polls and toggles must not pull the page back to this step.
        // oxlint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    return (
        <li
            ref={itemRef}
            className={cn('flex gap-3 min-w-0 scroll-mt-4', skipped && 'opacity-60')}
            data-attr="user-journey-run-step"
            data-step-status={step.status}
        >
            <div className="flex flex-col items-center shrink-0">
                <LemonBadge.Number
                    count={step.index + 1}
                    status={BADGE_STATUS[step.status]}
                    size="medium"
                    maxDigits={2}
                />
                {!isLast ? <div className="w-px flex-1 bg-border my-1" /> : null}
            </div>
            <div className="flex flex-col gap-2 min-w-0 flex-1 pb-6">
                <div className="flex items-start gap-x-4 gap-y-1 flex-wrap justify-between">
                    <JourneyStepSummary step={step.step} />
                    <div className="flex items-center gap-2 flex-wrap shrink-0">
                        {step.visual_change === 'changed' ? <LemonTag type="warning">Looks different</LemonTag> : null}
                        {step.status === 'passed' ? <LemonTag type="success">Passed</LemonTag> : null}
                        {step.status === 'failed' ? <LemonTag type="danger">Failed</LemonTag> : null}
                        {skipped ? <LemonTag type="muted">Skipped</LemonTag> : null}
                        {step.duration_ms !== null ? (
                            <span className="text-xs text-secondary" translate="no">
                                {humanFriendlyMilliseconds(step.duration_ms)}
                            </span>
                        ) : null}
                    </div>
                </div>

                {step.status === 'failed' ? (
                    <LemonBanner type="error">
                        <div className="flex flex-col gap-1">
                            <span className="font-semibold">{failureReasonLabel(step.failure_reason)}</span>
                            {step.message ? <span className="font-normal">{step.message}</span> : null}
                        </div>
                    </LemonBanner>
                ) : skipped ? (
                    <span className="text-xs text-secondary">
                        Skipped because an earlier step failed, so the browser wasn't on the page this step needs.
                    </span>
                ) : step.message ? (
                    <span className="text-xs text-secondary">{step.message}</span>
                ) : null}

                {hasScreenshot ? (
                    <div className="flex flex-col gap-2 items-start min-w-0">
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={isOpen ? <IconChevronDown /> : <IconChevronRight />}
                            onClick={() => setStepOpen(step.index, !isOpen)}
                            data-attr="user-journey-run-step-toggle"
                        >
                            {isOpen ? 'Hide screenshot' : 'Show screenshot'}
                        </LemonButton>
                        {isOpen ? (
                            // Screenshot URLs expire. The DOM `error` event doesn't bubble, but React passes an image's
                            // error up its own tree, so this wrapper hears it from inside the viewer.
                            <div className="w-full min-w-0" onError={screenshotFailedToLoad}>
                                <VisualImageDiffViewer
                                    baselineUrl={step.baseline_screenshot_url}
                                    currentUrl={step.screenshot_url}
                                    diffUrl={step.diff_screenshot_url}
                                    diffPercentage={step.diff_percentage}
                                    result={
                                        step.baseline_screenshot_url && step.visual_change !== 'new'
                                            ? (step.visual_change ?? 'unchanged')
                                            : 'new'
                                    }
                                    imageWidth={run.viewport_width}
                                    imageHeight={run.viewport_height}
                                    mode={comparisonMode}
                                    onModeChange={setComparisonMode}
                                />
                            </div>
                        ) : null}
                    </div>
                ) : null}
            </div>
        </li>
    )
}
