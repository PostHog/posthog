import { useMemo } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { percentage } from 'lib/utils/numbers'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { midEllipsis, pluralize } from 'lib/utils/strings'

import { PathsV2AnchorType } from '~/queries/schema/schema-general'

import { CARD_HEIGHT, CARD_WIDTH, COLUMN_GAP, cardKey, computeJourneyGridGeometry } from './journeyGridGeometry'
import {
    JourneyChainHighlight,
    JourneyGridModel,
    JourneyGridRibbon,
    JourneyGridRow,
    JourneyGridRowKind,
    ribbonPath,
} from './journeyGridModel'

const MAX_LABEL_CHARS = 30
const RIBBON_OPACITY = 0.15
const RIBBON_OPACITY_ON_CHAIN = 0.4
const RIBBON_OPACITY_DIMMED = 0.06

/** End-anchored grids read backward in time from the anchor column, so "Step n" would label the
 * columns in the wrong direction. */
function columnHeading(stepIndex: number, anchorType?: PathsV2AnchorType | null): string {
    if (anchorType === PathsV2AnchorType.End) {
        return stepIndex === 0 ? 'Last step' : `${pluralize(stepIndex, 'step')} earlier`
    }
    return `Step ${stepIndex + 1}`
}

export function JourneyGrid({
    model,
    isAnchored,
    anchorType,
    nodeColor,
    chainHighlight,
    onCardClick,
    onCardHover,
    onRibbonClick,
    onRibbonHover,
    onGridLeave,
}: {
    model: JourneyGridModel
    isAnchored: boolean
    anchorType?: PathsV2AnchorType | null
    nodeColor: string
    chainHighlight?: JourneyChainHighlight | null
    onCardClick?: (stepIndex: number, row: JourneyGridRow) => void
    onCardHover?: (stepIndex: number, row: JourneyGridRow) => void
    onRibbonClick?: (ribbon: JourneyGridRibbon) => void
    onRibbonHover?: (ribbon: JourneyGridRibbon) => void
    onGridLeave?: () => void
}): JSX.Element {
    const { cards, ribbons, chartWidth, chartHeight } = useMemo(() => computeJourneyGridGeometry(model), [model])

    const ribbonOpacity = (ribbon: JourneyGridRibbon): number => {
        if (!chainHighlight) {
            return RIBBON_OPACITY
        }
        return chainHighlight.ribbonKeys.has(ribbon.key) ? RIBBON_OPACITY_ON_CHAIN : RIBBON_OPACITY_DIMMED
    }

    return (
        <div className="overflow-auto p-4" data-attr="journey-grid" onMouseLeave={onGridLeave}>
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className="relative" style={{ width: chartWidth, height: chartHeight }}>
                <svg width={chartWidth} height={chartHeight} className="absolute inset-0 pointer-events-none">
                    {ribbons.map(({ ribbon, sourceThickness, targetThickness, fromX, fromY, toX, toY }) => (
                        <Tooltip
                            key={ribbon.key}
                            title={
                                <div className="flex flex-col gap-0.5">
                                    <span className="font-semibold">
                                        {ribbon.sourceLabel} → {ribbon.targetLabel}
                                    </span>
                                    <span>
                                        {pluralize(ribbon.count, 'person', 'people')} (
                                        {percentage(ribbon.fractionOfSource, 1)} of {ribbon.sourceLabel})
                                    </span>
                                </div>
                            }
                        >
                            <path
                                d={ribbonPath(fromX, fromY, sourceThickness, toX, toY, targetThickness)}
                                fill={nodeColor}
                                opacity={ribbonOpacity(ribbon)}
                                className={`pointer-events-auto hover:opacity-40 transition-opacity ${
                                    onRibbonClick ? 'cursor-pointer' : ''
                                }`}
                                data-attr="journey-grid-ribbon"
                                role={onRibbonClick ? 'button' : undefined}
                                tabIndex={onRibbonClick ? 0 : undefined}
                                aria-label={
                                    onRibbonClick
                                        ? `${ribbon.sourceLabel} → ${ribbon.targetLabel}, ${pluralize(
                                              ribbon.count,
                                              'person',
                                              'people'
                                          )}`
                                        : undefined
                                }
                                onClick={onRibbonClick ? () => onRibbonClick(ribbon) : undefined}
                                onMouseEnter={() => onRibbonHover?.(ribbon)}
                                onFocus={() => onRibbonHover?.(ribbon)}
                                onKeyDown={
                                    onRibbonClick
                                        ? (event) => {
                                              if (event.key === 'Enter' || event.key === ' ') {
                                                  event.preventDefault()
                                                  onRibbonClick(ribbon)
                                              }
                                          }
                                        : undefined
                                }
                            />
                        </Tooltip>
                    ))}
                </svg>

                {model.columns.map((column, columnIndex) => (
                    <div
                        key={`header-${column.stepIndex}`}
                        className="absolute text-xs font-semibold text-secondary"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ left: columnIndex * (CARD_WIDTH + COLUMN_GAP), top: 0, width: CARD_WIDTH }}
                    >
                        {columnHeading(column.stepIndex, anchorType)}
                    </div>
                ))}

                {cards.map(({ row, stepIndex, x, y }) => (
                    <JourneyCard
                        key={cardKey(stepIndex, row.key)}
                        row={row}
                        x={x}
                        y={y}
                        isAnchored={isAnchored}
                        nodeColor={nodeColor}
                        chainCount={
                            chainHighlight ? chainHighlight.countByCardKey[cardKey(stepIndex, row.key)] : undefined
                        }
                        chainFraction={
                            chainHighlight ? chainHighlight.fractionByCardKey[cardKey(stepIndex, row.key)] : undefined
                        }
                        dimmed={
                            !!chainHighlight && chainHighlight.countByCardKey[cardKey(stepIndex, row.key)] === undefined
                        }
                        onClick={onCardClick ? () => onCardClick(stepIndex, row) : undefined}
                        onMouseEnter={onCardHover ? () => onCardHover(stepIndex, row) : undefined}
                    />
                ))}
            </div>
        </div>
    )
}

const CARD_STYLES: Record<JourneyGridRowKind, { container: string; text: string; dataAttr: string }> = {
    item: { container: 'border bg-surface-primary', text: '', dataAttr: 'journey-grid-node' },
    other: { container: 'border border-dashed bg-surface-primary', text: '', dataAttr: 'journey-grid-other-row' },
    dropOff: { container: 'border border-transparent', text: 'text-secondary', dataAttr: 'journey-grid-drop-off-row' },
}

function dropOffTooltip(isAnchored: boolean): string {
    if (isAnchored) {
        return 'People whose journey ends at this step.'
    }
    return (
        'People whose journey ends at this step. ' +
        'A pause longer than the inactivity gap starts a new journey, so one person can have several journeys. ' +
        'The same person can appear in several rows and end journeys in more than one column, ' +
        'so percentages can add up to more than 100%.'
    )
}

function JourneyCard({
    row,
    x,
    y,
    isAnchored,
    nodeColor,
    chainCount,
    chainFraction,
    dimmed,
    onClick,
    onMouseEnter,
}: {
    row: JourneyGridRow
    x: number
    y: number
    isAnchored: boolean
    nodeColor: string
    /** The active chain's count for this card; set only while the card is on the hovered chain. */
    chainCount?: number
    /** The chain count's share of the column total, so the bar describes the number shown above it. */
    chainFraction?: number
    dimmed?: boolean
    onClick?: () => void
    onMouseEnter?: () => void
}): JSX.Element {
    const styles = CARD_STYLES[row.kind]
    const onChain = chainCount !== undefined
    const tooltip =
        row.kind === 'dropOff' ? (
            dropOffTooltip(isAnchored)
        ) : row.kind === 'other' ? (
            'Less common steps at this position, grouped together.'
        ) : (
            <>
                {row.label}
                {row.item?.label != null && <span className="text-muted"> ({row.item.event})</span>}
            </>
        )

    return (
        <div
            className={`absolute rounded px-2 py-1.5 transition-opacity ${styles.container} ${
                onClick ? 'cursor-pointer' : ''
            } ${dimmed ? 'opacity-40' : ''}`}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: x,
                top: y,
                width: CARD_WIDTH,
                height: CARD_HEIGHT,
                ...(onChain ? { boxShadow: `0 0 0 2px ${nodeColor}` } : {}),
            }}
            data-attr={styles.dataAttr}
            role={onClick ? 'button' : undefined}
            tabIndex={onClick ? 0 : undefined}
            onClick={onClick}
            onMouseEnter={onMouseEnter}
            onKeyDown={
                onClick
                    ? (event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault()
                              onClick()
                          }
                      }
                    : undefined
            }
        >
            <Tooltip title={tooltip}>
                <div className={`text-xs font-semibold truncate ${styles.text}`}>
                    {midEllipsis(row.label, MAX_LABEL_CHARS)}
                </div>
            </Tooltip>
            <div className="flex items-baseline gap-1.5 mt-0.5">
                <span className={`text-sm font-semibold ${styles.text}`}>
                    {humanFriendlyNumber(onChain ? chainCount : row.count)}
                </span>
                {!onChain && <span className="text-xs text-secondary">{percentage(row.fraction, 1)}</span>}
                {onChain && <span className="text-xs text-secondary">on this path</span>}
            </div>
            {row.kind !== 'dropOff' && (
                <LemonProgress
                    percent={Math.max(2, (onChain ? (chainFraction ?? 0) : row.fraction) * 100)}
                    strokeColor={row.kind === 'other' ? 'var(--color-gray-400)' : nodeColor}
                    bgColor="var(--color-fill-secondary)"
                    smoothing={false}
                    className="mt-1"
                />
            )}
        </div>
    )
}
