/* eslint-disable react/forbid-dom-props */
import clsx from 'clsx'

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
}: StepDecorationsProps): JSX.Element {
    const layout = useChartLayout<FunnelBarHorizontalSegmentMeta>()
    const { plotTop, plotLeft, plotHeight, plotWidth } = layout.dimensions
    const rowHeight = steps.length > 0 ? plotHeight / steps.length : 0

    return (
        <>
            {steps.map((step, stepIndex) => {
                const rowTop = plotTop + stepIndex * rowHeight
                const isOptional = isStepOptional(stepIndex + 1)
                const isFirstStep = stepIndex === 0
                const isUnordered = funnelsFilter?.funnelOrderType === StepOrderValue.UNORDERED
                const gapHeight = rowHeight * gapFraction

                const dimRow = isOptional ? 'opacity-60' : ''

                // Conversion-% label for the step, placed in the empty track just past the bar so it
                // never paints over breakdown segments. The fill fraction matches the bar's filled
                // width (value series / stack total). Omitted when the bar leaves no room for it.
                const barCenterY = rowHeight / 2
                const fillFraction = Math.max(0, Math.min(1, step.conversionRates.fromBasisStep))
                const fillPx = fillFraction * plotWidth
                const pctLabel = formatConvertedPercentage(step)
                const pctFitsTrack = plotWidth - fillPx >= pctLabel.length * 8 + 16

                const halfGlyphPx = GLYPH_HEIGHT_PX / 2
                // Align the step glyph with the header title rather than the bar's vertical centre,
                // so the numbered circle reads inline with the step title. The small nudge past the
                // line-box centre matches the title text's optical centre (text sits low in its box).
                const glyphCenter = gapHeight / 2 + 4
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
                        // Clicks on the overlay's own controls (kebab, value buttons) must not bubble to
                        // the chart wrapper's click handler, which would also open the persons modal.
                        onClick={(e) => e.stopPropagation()}
                        style={{ position: 'absolute', top: rowTop, left: 0, width: '100%', height: rowHeight }}
                        className="pointer-events-none [&_[role=button]]:pointer-events-auto [&_a]:pointer-events-auto [&_button]:pointer-events-auto"
                    >
                        <div
                            style={{ position: 'absolute', top: 0, left: 0, width: plotLeft, height: rowHeight }}
                            className={clsx(isOptional && 'opacity-70')}
                        >
                            {stepIndex > 0 && (
                                <div style={{ ...lineStyle, top: 0, height: Math.max(0, glyphCenter - halfGlyphPx) }} />
                            )}
                            {isOptional && hasOptionalSteps && (
                                <div
                                    className="absolute left-[calc(50%-1px)] w-[2px] bg-[var(--color-border-primary)] opacity-50 z-[1]"
                                    style={{ top: 0, height: rowHeight }}
                                />
                            )}
                            {isOptional && (
                                <div
                                    className="absolute left-[calc(50%-1px)] w-6 h-[2px] bg-[var(--color-border-primary)] opacity-50"
                                    style={{ top: glyphCenter - 1 }}
                                />
                            )}
                            <div
                                className={clsx('absolute z-10 select-none', isOptional && 'ml-6')}
                                style={{
                                    top: glyphCenter,
                                    left: '50%',
                                    transform: 'translate(-50%, -50%)',
                                    pointerEvents: 'auto',
                                }}
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
                                <div style={{ ...lineStyle, top: glyphCenter + halfGlyphPx, bottom: 0 }} />
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
                            className={clsx('flex flex-wrap items-center justify-between leading-5', dimRow)}
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
                                {!isUnordered && stepIndex > 0 && step.action_id === steps[stepIndex - 1].action_id && (
                                    // pointer-events-auto so the click hits the overlay (then stops) instead of
                                    // falling through to the canvas and opening the persons modal.
                                    <span className="pointer-events-auto inline-flex items-center">
                                        <DuplicateStepIndicator />
                                    </span>
                                )}
                                <FunnelStepMore stepIndex={stepIndex} className="ml-2" />
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
                        </header>

                        {pctFitsTrack && (
                            <div
                                className={clsx('absolute text-sm font-bold whitespace-nowrap', dimRow)}
                                style={{
                                    top: barCenterY,
                                    left: plotLeft + fillPx + 8,
                                    transform: 'translateY(-50%)',
                                    color: 'var(--text-3000)',
                                }}
                            >
                                {pctLabel}
                            </div>
                        )}

                        <div
                            style={{
                                position: 'absolute',
                                top: rowHeight - gapHeight,
                                left: plotLeft,
                                width: plotWidth,
                                height: gapHeight,
                            }}
                            className={clsx('flex flex-wrap items-center gap-2 leading-5', dimRow)}
                        >
                            <Tooltip
                                title={getTooltipTitleForConverted(funnelsFilter, aggregationTargetLabel, stepIndex)}
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
                )
            })}
        </>
    )
}
