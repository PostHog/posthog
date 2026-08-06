import { useMemo } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { percentage } from 'lib/utils/numbers'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { midEllipsis, pluralize } from 'lib/utils/strings'

import {
    JourneyChainHighlight,
    JourneyGridModel,
    JourneyGridRibbon,
    JourneyGridRow,
    JourneyGridRowKind,
    ribbonPath,
} from './journeyGridModel'

const CARD_WIDTH = 224
const COLUMN_GAP = 104
const CARD_HEIGHT = 66
const ROW_GAP = 14
const HEADER_HEIGHT = 28
const PORT_TOP_OFFSET = 6
const PORT_GAP = 2
const MAX_RIBBON_THICKNESS = 36
const MIN_RIBBON_THICKNESS = 2
const MAX_LABEL_CHARS = 30
const RIBBON_OPACITY = 0.15
const RIBBON_OPACITY_ON_CHAIN = 0.4
const RIBBON_OPACITY_DIMMED = 0.06

interface CardGeometry {
    row: JourneyGridRow
    stepIndex: number
    x: number
    y: number
}

interface RibbonGeometry {
    ribbon: JourneyGridRibbon
    thickness: number
    fromX: number
    fromY: number
    toX: number
    toY: number
}

function cardKey(stepIndex: number, rowKey: string): string {
    return `${stepIndex}:${rowKey}`
}

export function JourneyGrid({
    model,
    isAnchored,
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
    nodeColor: string
    chainHighlight?: JourneyChainHighlight | null
    onCardClick?: (stepIndex: number, row: JourneyGridRow) => void
    onCardHover?: (stepIndex: number, row: JourneyGridRow) => void
    onRibbonClick?: (ribbon: JourneyGridRibbon) => void
    onRibbonHover?: (ribbon: JourneyGridRibbon) => void
    onGridLeave?: () => void
}): JSX.Element {
    const { cards, ribbons, chartWidth, chartHeight } = useMemo(() => {
        const cardByKey = new Map<string, CardGeometry>()
        const cards: CardGeometry[] = []
        let maxCardBottom = 0
        model.columns.forEach((column, columnIndex) => {
            let y = HEADER_HEIGHT
            for (const row of column.rows) {
                const card = { row, stepIndex: column.stepIndex, x: columnIndex * (CARD_WIDTH + COLUMN_GAP), y }
                cardByKey.set(cardKey(column.stepIndex, row.key), card)
                cards.push(card)
                y += CARD_HEIGHT + ROW_GAP
            }
            maxCardBottom = Math.max(maxCardBottom, y - ROW_GAP)
        })

        const thicknessFor = (count: number): number =>
            Math.max(MIN_RIBBON_THICKNESS, (count / Math.max(model.maxRibbonCount, 1)) * MAX_RIBBON_THICKNESS)

        // Resolve each ribbon's cards once, then stack the ports on each card side in the vertical
        // order of the connected cards, so ribbons out of one card never cross at the card edge.
        const resolvedRibbons = model.ribbons.flatMap((ribbon) => {
            const sourceCardKey = cardKey(ribbon.sourceStep, ribbon.sourceKey)
            const targetCardKey = cardKey(ribbon.sourceStep + 1, ribbon.targetKey)
            const source = cardByKey.get(sourceCardKey)
            const target = cardByKey.get(targetCardKey)
            return source && target ? [{ ribbon, source, target, sourceCardKey, targetCardKey }] : []
        })
        resolvedRibbons.sort((a, b) => a.source.y - b.source.y || a.target.y - b.target.y)

        const outCursor = new Map<string, number>()
        const inCursor = new Map<string, number>()
        const ribbons: RibbonGeometry[] = resolvedRibbons.map(
            ({ ribbon, source, target, sourceCardKey, targetCardKey }) => {
                const thickness = thicknessFor(ribbon.count)
                const fromY = source.y + PORT_TOP_OFFSET + (outCursor.get(sourceCardKey) ?? 0)
                const toY = target.y + PORT_TOP_OFFSET + (inCursor.get(targetCardKey) ?? 0)
                outCursor.set(sourceCardKey, (outCursor.get(sourceCardKey) ?? 0) + thickness + PORT_GAP)
                inCursor.set(targetCardKey, (inCursor.get(targetCardKey) ?? 0) + thickness + PORT_GAP)
                return {
                    ribbon,
                    thickness,
                    fromX: source.x + CARD_WIDTH,
                    fromY,
                    toX: target.x,
                    toY,
                }
            }
        )

        const chartWidth = model.columns.length * (CARD_WIDTH + COLUMN_GAP) - COLUMN_GAP
        const chartHeight = maxCardBottom + 16
        return { cards, ribbons, chartWidth, chartHeight }
    }, [model])

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
                    {ribbons.map(({ ribbon, thickness, fromX, fromY, toX, toY }) => (
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
                                d={ribbonPath(fromX, fromY, thickness, toX, toY, thickness)}
                                fill={nodeColor}
                                opacity={ribbonOpacity(ribbon)}
                                // The transparent stroke widens the hover target without changing the
                                // drawn shape, so hair-thin ribbons can still be hovered for a tooltip.
                                stroke="transparent"
                                strokeWidth={8}
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
                        Step {column.stepIndex + 1}
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
        'Every number counts unique people, and one person can appear in several rows of a column, ' +
        'so the percentages in a column can add up to more than 100%.'
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
        // The whole card is the tooltip trigger — a label-only trigger makes the tooltip vanish
        // as soon as the pointer moves onto the count or progress bar within the card.
        <Tooltip title={tooltip}>
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
                <div className={`text-xs font-semibold truncate ${styles.text}`}>
                    {midEllipsis(row.label, MAX_LABEL_CHARS)}
                </div>
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
        </Tooltip>
    )
}
