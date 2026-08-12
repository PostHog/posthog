import { useMemo } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { midEllipsis, pluralize } from 'lib/utils/strings'

import {
    BAR_WIDTH,
    COLUMN_PITCH,
    JourneyLayoutRow,
    LABEL_BLOCK_HEIGHT,
    buildJourneyGridLayout,
} from './journeyGridLayout'
import {
    JourneyChainHighlight,
    JourneyGridModel,
    JourneyGridRibbon,
    JourneyGridRow,
    JourneyGridRowKind,
    ribbonPath,
} from './journeyGridModel'

const MAX_LABEL_CHARS = 34
const LABEL_WIDTH = COLUMN_PITCH - 24
const RIBBON_OPACITY = 0.18
const RIBBON_OPACITY_ON_CHAIN = 0.5
const RIBBON_OPACITY_DIMMED = 0.05

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
    const layout = useMemo(() => buildJourneyGridLayout(model), [model])

    const ribbonOpacity = (ribbon: JourneyGridRibbon): number => {
        if (!chainHighlight) {
            return RIBBON_OPACITY
        }
        return chainHighlight.ribbonKeys.has(ribbon.key) ? RIBBON_OPACITY_ON_CHAIN : RIBBON_OPACITY_DIMMED
    }

    return (
        <div className="overflow-auto p-4" data-attr="journey-grid" onMouseLeave={onGridLeave}>
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className="relative" style={{ width: layout.width, height: layout.height }}>
                <svg width={layout.width} height={layout.height} className="absolute inset-0 pointer-events-none">
                    {layout.ribbons.map(({ ribbon, fromX, fromY, fromThickness, toX, toY, toThickness }) => (
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
                                d={ribbonPath(fromX, fromY, fromThickness, toX, toY, toThickness)}
                                fill={nodeColor}
                                opacity={ribbonOpacity(ribbon)}
                                // The transparent stroke widens the hover target without changing the
                                // drawn shape, so hair-thin ribbons can still be hovered for a tooltip.
                                stroke="transparent"
                                strokeWidth={8}
                                className={`pointer-events-auto hover:opacity-50 transition-opacity ${
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
                        style={{ left: columnIndex * COLUMN_PITCH, top: 0, width: LABEL_WIDTH }}
                    >
                        Step {column.stepIndex + 1}
                    </div>
                ))}

                {layout.rows.map((layoutRow) => (
                    <JourneyNode
                        key={cardKey(layoutRow.stepIndex, layoutRow.row.key)}
                        layoutRow={layoutRow}
                        isAnchored={isAnchored}
                        nodeColor={nodeColor}
                        chainCount={
                            chainHighlight
                                ? chainHighlight.countByCardKey[cardKey(layoutRow.stepIndex, layoutRow.row.key)]
                                : undefined
                        }
                        dimmed={
                            !!chainHighlight &&
                            chainHighlight.countByCardKey[cardKey(layoutRow.stepIndex, layoutRow.row.key)] === undefined
                        }
                        onClick={onCardClick ? () => onCardClick(layoutRow.stepIndex, layoutRow.row) : undefined}
                        onMouseEnter={onCardHover ? () => onCardHover(layoutRow.stepIndex, layoutRow.row) : undefined}
                    />
                ))}
            </div>
        </div>
    )
}

const NODE_DATA_ATTRS: Record<JourneyGridRowKind, string> = {
    item: 'journey-grid-node',
    other: 'journey-grid-other-row',
    dropOff: 'journey-grid-drop-off-row',
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

function JourneyNode({
    layoutRow,
    isAnchored,
    nodeColor,
    chainCount,
    dimmed,
    onClick,
    onMouseEnter,
}: {
    layoutRow: JourneyLayoutRow
    isAnchored: boolean
    nodeColor: string
    /** The active chain's count for this node; set only while the node is on the hovered chain. */
    chainCount?: number
    dimmed?: boolean
    onClick?: () => void
    onMouseEnter?: () => void
}): JSX.Element {
    const { row, x, labelY, barHeight } = layoutRow
    const isDropOff = row.kind === 'dropOff'
    const onChain = chainCount !== undefined
    const tooltip = isDropOff ? (
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
        // The whole node is the tooltip trigger — a label-only trigger makes the tooltip vanish
        // as soon as the pointer moves onto the count or bar within the node.
        <Tooltip title={tooltip}>
            <div
                className={`absolute transition-opacity ${onClick ? 'cursor-pointer' : ''} ${
                    dimmed ? 'opacity-40' : ''
                }`}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: x, top: labelY, width: LABEL_WIDTH }}
                data-attr={NODE_DATA_ATTRS[row.kind]}
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
                {/* Fixed-height label block: the layout attaches ribbons at labelY + LABEL_BLOCK_HEIGHT,
                    so the bar's top must not drift with text flow. */}
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div className="overflow-hidden" style={{ height: isDropOff ? undefined : LABEL_BLOCK_HEIGHT }}>
                    <div className={`text-xs font-semibold truncate ${isDropOff ? 'text-secondary' : ''}`}>
                        {midEllipsis(row.label, MAX_LABEL_CHARS)}
                    </div>
                    <div className="flex items-baseline gap-1.5">
                        <span className={`text-sm font-semibold ${isDropOff ? 'text-secondary' : ''}`}>
                            {humanFriendlyNumber(onChain ? chainCount : row.count)}
                        </span>
                        {!onChain && <span className="text-xs text-secondary">{percentage(row.fraction, 1)}</span>}
                        {onChain && <span className="text-xs text-secondary">on this path</span>}
                    </div>
                </div>
                {!isDropOff && (
                    <div
                        className="rounded"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            width: BAR_WIDTH,
                            height: barHeight,
                            backgroundColor: row.kind === 'other' ? 'var(--color-gray-400)' : nodeColor,
                            ...(onChain
                                ? {
                                      boxShadow: `0 0 0 2px var(--color-bg-surface-primary), 0 0 0 4px ${nodeColor}`,
                                  }
                                : {}),
                        }}
                    />
                )}
            </div>
        </Tooltip>
    )
}
