import { useMemo } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { JourneyGridModel, JourneyGridRibbon, JourneyGridRow, middleEllipsis, ribbonPath } from './journeyGridModel'

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
}: {
    model: JourneyGridModel
    isAnchored: boolean
    nodeColor: string
}): JSX.Element {
    const { cards, ribbons, chartWidth, chartHeight } = useMemo(() => {
        const cards = new Map<string, CardGeometry>()
        model.columns.forEach((column, columnIndex) => {
            let y = HEADER_HEIGHT
            for (const row of column.rows) {
                cards.set(cardKey(column.stepIndex, row.key), {
                    row,
                    stepIndex: column.stepIndex,
                    x: columnIndex * (CARD_WIDTH + COLUMN_GAP),
                    y,
                })
                y += CARD_HEIGHT + ROW_GAP
            }
        })

        const thicknessFor = (count: number): number =>
            Math.max(MIN_RIBBON_THICKNESS, (count / Math.max(model.maxRibbonCount, 1)) * MAX_RIBBON_THICKNESS)

        // Stack the ports on each card side in the vertical order of the connected cards, so
        // ribbons out of one card never cross each other at the card edge.
        const sortedRibbons = [...model.ribbons].sort(
            (a, b) =>
                (cards.get(cardKey(a.sourceStep, a.sourceKey))?.y ?? 0) -
                    (cards.get(cardKey(b.sourceStep, b.sourceKey))?.y ?? 0) ||
                (cards.get(cardKey(a.sourceStep + 1, a.targetKey))?.y ?? 0) -
                    (cards.get(cardKey(b.sourceStep + 1, b.targetKey))?.y ?? 0)
        )
        const outCursor = new Map<string, number>()
        const inCursor = new Map<string, number>()
        const ribbons: RibbonGeometry[] = []
        for (const ribbon of sortedRibbons) {
            const source = cards.get(cardKey(ribbon.sourceStep, ribbon.sourceKey))
            const target = cards.get(cardKey(ribbon.sourceStep + 1, ribbon.targetKey))
            if (!source || !target) {
                continue
            }
            const thickness = thicknessFor(ribbon.count)
            const sourceCardKey = cardKey(ribbon.sourceStep, ribbon.sourceKey)
            const targetCardKey = cardKey(ribbon.sourceStep + 1, ribbon.targetKey)
            const fromY = source.y + PORT_TOP_OFFSET + (outCursor.get(sourceCardKey) ?? 0)
            const toY = target.y + PORT_TOP_OFFSET + (inCursor.get(targetCardKey) ?? 0)
            outCursor.set(sourceCardKey, (outCursor.get(sourceCardKey) ?? 0) + thickness + PORT_GAP)
            inCursor.set(targetCardKey, (inCursor.get(targetCardKey) ?? 0) + thickness + PORT_GAP)
            ribbons.push({
                ribbon,
                thickness,
                fromX: source.x + CARD_WIDTH,
                fromY,
                toX: target.x,
                toY,
            })
        }

        const chartWidth = model.columns.length * (CARD_WIDTH + COLUMN_GAP) - COLUMN_GAP
        const chartHeight = Math.max(...Array.from(cards.values()).map((card) => card.y + CARD_HEIGHT), 0) + 16
        return { cards, ribbons, chartWidth, chartHeight }
    }, [model])

    return (
        <div className="overflow-auto p-4" data-attr="journey-grid">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className="relative" style={{ width: chartWidth, height: chartHeight }}>
                <svg width={chartWidth} height={chartHeight} className="absolute inset-0 pointer-events-none">
                    {ribbons.map(({ ribbon, thickness, fromX, fromY, toX, toY }) => (
                        <path
                            key={ribbon.key}
                            d={ribbonPath(fromX, fromY, thickness, toX, toY, thickness)}
                            fill={nodeColor}
                            opacity={0.15}
                            className="pointer-events-auto hover:opacity-40 transition-opacity"
                        >
                            <title>
                                {`${ribbon.sourceLabel} → ${ribbon.targetLabel}: ${humanFriendlyNumber(
                                    ribbon.count
                                )} ${ribbon.count === 1 ? 'person' : 'people'} (${percentage(
                                    ribbon.fractionOfSource,
                                    1
                                )} of ${ribbon.sourceLabel})`}
                            </title>
                        </path>
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

                {Array.from(cards.values()).map(({ row, stepIndex, x, y }) => (
                    <JourneyCard
                        key={cardKey(stepIndex, row.key)}
                        row={row}
                        x={x}
                        y={y}
                        isAnchored={isAnchored}
                        nodeColor={nodeColor}
                    />
                ))}
            </div>
        </div>
    )
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
}: {
    row: JourneyGridRow
    x: number
    y: number
    isAnchored: boolean
    nodeColor: string
}): JSX.Element {
    const tooltip =
        row.kind === 'dropOff' ? (
            dropOffTooltip(isAnchored)
        ) : row.kind === 'other' ? (
            'Path items beyond the top rows at this step.'
        ) : (
            <>
                {row.label}
                {row.item?.label != null && <span className="text-muted"> ({row.item.event})</span>}
            </>
        )

    return (
        <div
            className={`absolute rounded px-2 py-1.5 ${
                row.kind === 'dropOff'
                    ? 'border border-transparent'
                    : row.kind === 'other'
                      ? 'border border-dashed bg-surface-primary'
                      : 'border bg-surface-primary'
            }`}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ left: x, top: y, width: CARD_WIDTH, height: CARD_HEIGHT }}
            data-attr={`journey-grid-${row.kind === 'item' ? 'node' : row.kind === 'other' ? 'other-row' : 'drop-off-row'}`}
        >
            <Tooltip title={tooltip}>
                <div className={`text-xs font-semibold truncate ${row.kind === 'dropOff' ? 'text-secondary' : ''}`}>
                    {middleEllipsis(row.label, MAX_LABEL_CHARS)}
                </div>
            </Tooltip>
            <div className="flex items-baseline gap-1.5 mt-0.5">
                <span className={`text-sm font-semibold ${row.kind === 'dropOff' ? 'text-secondary' : ''}`}>
                    {humanFriendlyNumber(row.count)}
                </span>
                <span className="text-xs text-secondary">{percentage(row.fraction, 1)}</span>
            </div>
            {row.kind !== 'dropOff' && (
                <div className="h-1 rounded-full bg-fill-secondary mt-1.5">
                    <div
                        className="h-1 rounded-full"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            width: `${Math.max(2, row.fraction * 100)}%`,
                            backgroundColor: row.kind === 'other' ? 'var(--color-gray-400)' : nodeColor,
                        }}
                    />
                </div>
            )}
        </div>
    )
}
