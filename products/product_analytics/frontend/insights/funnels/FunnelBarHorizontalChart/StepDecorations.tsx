/* eslint-disable react/forbid-dom-props */
import clsx from 'clsx'
import { useLayoutEffect, useRef } from 'react'

import { IconInfinity } from '@posthog/icons'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { useChartLayout } from 'lib/hog-charts'
import { IconTrendingFlat, IconTrendingFlatDown } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration } from 'lib/utils'
import { DuplicateStepIndicator } from 'scenes/funnels/FunnelBarHorizontal/DuplicateStepIndicator'
import { FunnelStepMore } from 'scenes/funnels/FunnelStepMore'
import {
    formatConvertedCount,
    formatConvertedPercentage,
    formatDroppedOffCount,
    formatDroppedOffPercentage,
    getTooltipTitleForConverted,
    getTooltipTitleForDroppedOff,
} from 'scenes/funnels/funnelUtils'
import { ValueInspectorButton } from 'scenes/funnels/ValueInspectorButton'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'

import type { FunnelsFilter } from '~/queries/schema/schema-general'
import { type FunnelStepWithConversionMetrics, StepOrderValue } from '~/types'

import type { FunnelBarHorizontalSegmentMeta } from './funnelBarHorizontalTransforms'

const GLYPH_HEIGHT_PX = 23

interface StepDecorationsProps {
    steps: FunnelStepWithConversionMetrics[]
    funnelsFilter: FunnelsFilter | null | undefined
    aggregationTargetLabel: { singular: string; plural: string }
    isStepOptional: (step: number) => boolean
    hasOptionalSteps: boolean
    showPersonsModal: boolean
    openPersonsModalForStep: (args: { step: FunnelStepWithConversionMetrics; converted: boolean }) => void
    /** Fraction of each band reserved for gap. Header and metadata rows each occupy half this gap. */
    gapFraction: number
    /** Reports the tallest header/footer content (px) so the parent can grow rows to fit wrapped text. */
    onMeasureGap?: (gapPx: number) => void
}

export function StepDecorations({
    steps,
    funnelsFilter,
    aggregationTargetLabel,
    isStepOptional,
    hasOptionalSteps,
    showPersonsModal,
    openPersonsModalForStep,
    gapFraction,
    onMeasureGap,
}: StepDecorationsProps): JSX.Element {
    const layout = useChartLayout<FunnelBarHorizontalSegmentMeta>()
    const { plotTop, plotLeft, plotHeight, plotWidth } = layout.dimensions
    const rowHeight = steps.length > 0 ? plotHeight / steps.length : 0

    // The measured divs flow at natural height inside their fixed-height slots, so their offsetHeight
    // is the unconstrained content height — the max drives the parent's row height. Wrapping depends
    // only on plotWidth, so this converges in a single pass and never loops.
    const slotRefs = useRef<Map<string, HTMLDivElement>>(new Map())
    const setSlotRef =
        (key: string) =>
        (el: HTMLDivElement | null): void => {
            if (el) {
                slotRefs.current.set(key, el)
            } else {
                slotRefs.current.delete(key)
            }
        }
    useLayoutEffect(() => {
        if (!onMeasureGap || plotWidth <= 0) {
            return
        }
        let tallest = 0
        for (const el of slotRefs.current.values()) {
            tallest = Math.max(tallest, el.offsetHeight)
        }
        if (tallest > 0) {
            onMeasureGap(tallest)
        }
    }, [onMeasureGap, plotWidth, steps])

    return (
        <>
            {steps.map((step, stepIndex) => {
                const rowTop = plotTop + stepIndex * rowHeight
                const isOptional = isStepOptional(stepIndex + 1)
                const isFirstStep = stepIndex === 0
                const isUnordered = funnelsFilter?.funnelOrderType === StepOrderValue.UNORDERED
                const gapHeight = rowHeight * gapFraction

                const dimRow = isOptional ? 'opacity-60' : ''

                const halfGlyph = `${GLYPH_HEIGHT_PX / 2}px`
                const lineStyle = {
                    position: 'absolute' as const,
                    left: 'calc(50% - 1px)',
                    width: '2px',
                    borderRight: '2px solid var(--color-border-primary)',
                    opacity: 0.5,
                }

                return (
                    <div
                        key={step.order}
                        style={{ position: 'absolute', top: rowTop, left: 0, width: '100%', height: rowHeight }}
                        className="pointer-events-none [&_[role=button]]:pointer-events-auto [&_a]:pointer-events-auto [&_button]:pointer-events-auto"
                    >
                        <div
                            style={{ position: 'absolute', top: 0, left: 0, width: plotLeft, height: rowHeight }}
                            className={clsx('flex flex-col items-center justify-center', isOptional && 'opacity-70')}
                        >
                            {stepIndex > 0 && (
                                <div style={{ ...lineStyle, top: 0, height: `calc(50% - ${halfGlyph})` }} />
                            )}
                            {isOptional && hasOptionalSteps && (
                                <div className="absolute top-0 left-[calc(50%-1px)] w-[2px] h-full bg-[var(--color-border-primary)] opacity-50 z-[1]" />
                            )}
                            {isOptional && (
                                <div className="absolute top-[calc(50%-1px)] left-[calc(50%-1px)] w-6 h-[2px] bg-[var(--color-border-primary)] opacity-50" />
                            )}
                            <div
                                className={clsx('relative z-10 select-none', isOptional && 'ml-6')}
                                style={{ pointerEvents: 'auto' }}
                            >
                                <SeriesGlyph variant="funnel-step-glyph">
                                    {isUnordered ? (
                                        <IconInfinity style={{ fill: 'var(--primary_alt)', width: 14 }} />
                                    ) : (
                                        step.order + 1
                                    )}
                                </SeriesGlyph>
                            </div>
                            {stepIndex < steps.length - 1 && (
                                <div style={{ ...lineStyle, top: `calc(50% + ${halfGlyph})`, bottom: 0 }} />
                            )}
                        </div>

                        <header
                            style={{
                                position: 'absolute',
                                top: 0,
                                left: plotLeft,
                                width: plotWidth,
                                height: gapHeight,
                            }}
                            className={clsx('flex items-center', dimRow)}
                        >
                            <div
                                ref={setSlotRef(`${stepIndex}-header`)}
                                className="flex w-full flex-wrap items-center justify-between leading-5"
                            >
                                <div className="flex items-center max-w-full grow">
                                    <div className="overflow-hidden font-bold break-words whitespace-normal">
                                        {isUnordered ? (
                                            <span>Completed {step.order + 1} steps</span>
                                        ) : (
                                            <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} allowWrap />
                                        )}
                                    </div>
                                    {isOptional ? <div className="ml-1 text-xs">(optional)</div> : null}
                                    {!isUnordered &&
                                        stepIndex > 0 &&
                                        step.action_id === steps[stepIndex - 1].action_id && <DuplicateStepIndicator />}
                                    <FunnelStepMore stepIndex={stepIndex} />
                                </div>
                                {step.average_conversion_time && step.average_conversion_time >= Number.EPSILON ? (
                                    <div
                                        className="text-secondary text-xs"
                                        title="Average time of conversion from previous step"
                                    >
                                        Avg time:{' '}
                                        <b>{humanFriendlyDuration(step.average_conversion_time, { maxUnits: 2 })}</b>
                                    </div>
                                ) : null}
                            </div>
                        </header>

                        <div
                            style={{
                                position: 'absolute',
                                top: rowHeight - gapHeight,
                                left: plotLeft,
                                width: plotWidth,
                                height: gapHeight,
                            }}
                            className={clsx('flex items-center', dimRow)}
                        >
                            <div
                                ref={setSlotRef(`${stepIndex}-footer`)}
                                className="flex w-full flex-wrap items-center gap-2 leading-5"
                            >
                                <Tooltip
                                    title={getTooltipTitleForConverted(
                                        funnelsFilter,
                                        aggregationTargetLabel,
                                        stepIndex
                                    )}
                                    placement="bottom"
                                >
                                    <ValueInspectorButton
                                        onClick={
                                            showPersonsModal
                                                ? () => openPersonsModalForStep({ step, converted: true })
                                                : undefined
                                        }
                                    >
                                        <IconTrendingFlat
                                            style={{ color: 'var(--success)' }}
                                            className="mr-1 text-xl align-bottom"
                                        />
                                        <b>{formatConvertedCount(step, aggregationTargetLabel)}</b>
                                    </ValueInspectorButton>{' '}
                                    {!isFirstStep && (
                                        <span className="text-secondary grow">
                                            {`(${formatConvertedPercentage(step)}) completed step`}
                                        </span>
                                    )}
                                </Tooltip>
                                {!isFirstStep && (
                                    <Tooltip
                                        title={getTooltipTitleForDroppedOff(funnelsFilter, aggregationTargetLabel)}
                                        placement="bottom"
                                    >
                                        <ValueInspectorButton
                                            onClick={
                                                showPersonsModal
                                                    ? () => openPersonsModalForStep({ step, converted: false })
                                                    : undefined
                                            }
                                        >
                                            <IconTrendingFlatDown
                                                style={{ color: 'var(--danger)' }}
                                                className="mr-1 text-xl align-bottom"
                                            />
                                            <b>{formatDroppedOffCount(step, aggregationTargetLabel)}</b>
                                        </ValueInspectorButton>{' '}
                                        <span className="text-secondary">
                                            {`(${formatDroppedOffPercentage(step)}) dropped off`}
                                        </span>
                                    </Tooltip>
                                )}
                            </div>
                        </div>
                    </div>
                )
            })}
        </>
    )
}
