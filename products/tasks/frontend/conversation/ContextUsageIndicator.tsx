import { JSX, useState } from 'react'

import { Popover } from '@posthog/lemon-ui'

import { CONTEXT_CATEGORIES, type ContextUsage, formatTokensCompact, getOverallUsageColor } from './contextUsage'

const CIRCLE_SIZE = 20
const STROKE_WIDTH = 2.5
const RADIUS = (CIRCLE_SIZE - STROKE_WIDTH) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

interface ContextUsageIndicatorProps {
    usage: ContextUsage | null
}

/**
 * Compact ring + token count showing how full the agent's context window is.
 * Clicking opens a breakdown popover. Renders nothing until the first
 * `usage_update` has arrived.
 *
 * Ported from PostHog Code's `ContextUsageIndicator` (Radix Popover swapped
 * for the lemon-ui `Popover`).
 */
export function ContextUsageIndicator({ usage }: ContextUsageIndicatorProps): JSX.Element | null {
    const [visible, setVisible] = useState(false)

    if (!usage) {
        return null
    }

    const { used, size, percentage } = usage
    const strokeDashoffset = CIRCUMFERENCE - (percentage / 100) * CIRCUMFERENCE
    const color = getOverallUsageColor(percentage)

    return (
        <Popover
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement="top-end"
            overlay={<ContextBreakdownContent usage={usage} />}
        >
            <button
                type="button"
                className="flex cursor-pointer select-none items-center gap-1 bg-transparent border-0 p-0"
                aria-label={`Context usage: ${percentage}%`}
                onClick={() => setVisible(!visible)}
            >
                <svg
                    width={CIRCLE_SIZE}
                    height={CIRCLE_SIZE}
                    className="-rotate-90 shrink-0"
                    role="img"
                    aria-hidden="true"
                >
                    <circle
                        cx={CIRCLE_SIZE / 2}
                        cy={CIRCLE_SIZE / 2}
                        r={RADIUS}
                        fill="none"
                        stroke="var(--border)"
                        strokeWidth={STROKE_WIDTH}
                    />
                    <circle
                        cx={CIRCLE_SIZE / 2}
                        cy={CIRCLE_SIZE / 2}
                        r={RADIUS}
                        fill="none"
                        stroke={color}
                        strokeWidth={STROKE_WIDTH}
                        strokeDasharray={CIRCUMFERENCE}
                        strokeDashoffset={strokeDashoffset}
                        strokeLinecap="round"
                    />
                </svg>
                <span className="text-[13px] text-muted tabular-nums whitespace-nowrap">
                    {formatTokensCompact(used)}/{formatTokensCompact(size)} · {percentage}%
                </span>
            </button>
        </Popover>
    )
}

export function ContextBreakdownContent({ usage }: { usage: ContextUsage }): JSX.Element {
    const { used, size, percentage, breakdown } = usage
    const fillColor = getOverallUsageColor(percentage)

    return (
        <div className="flex flex-col gap-3 min-w-70 p-3">
            <div className="flex items-center justify-between gap-4">
                <span className="font-medium text-[13px]">Context</span>
                <span className="text-muted text-xs tabular-nums">
                    ~{formatTokensCompact(used)} / {formatTokensCompact(size)} tokens
                </span>
            </div>

            <span className="font-semibold text-[15px]">{percentage}% full</span>

            {breakdown ? (
                <SegmentedBar breakdown={breakdown} total={used} fallback={fillColor} />
            ) : (
                <SinglePercentBar percentage={percentage} color={fillColor} />
            )}

            {breakdown ? (
                <div className="flex flex-col gap-2">
                    {CONTEXT_CATEGORIES.filter((cat) => breakdown[cat.key] > 0).map((cat) => (
                        <div key={cat.key} className="flex items-center justify-between text-[13px]">
                            <div className="flex items-center gap-2">
                                <span
                                    className="inline-block size-2.5 rounded-sm"
                                    style={{ backgroundColor: cat.color }}
                                />
                                <span>{cat.label}</span>
                            </div>
                            <span className="text-secondary tabular-nums">
                                {formatTokensCompact(breakdown[cat.key])}
                            </span>
                        </div>
                    ))}
                </div>
            ) : (
                <span className="text-muted text-xs">Detailed breakdown available after the first response</span>
            )}
        </div>
    )
}

function SegmentedBar({
    breakdown,
    total,
    fallback,
}: {
    breakdown: NonNullable<ContextUsage['breakdown']>
    total: number
    fallback: string
}): JSX.Element {
    if (total <= 0) {
        return <div className="h-1.5 w-full rounded-full bg-fill-secondary" />
    }

    const segmentSum = CONTEXT_CATEGORIES.reduce((acc, cat) => acc + Math.max(0, breakdown[cat.key]), 0)
    const denominator = Math.max(total, segmentSum)
    return (
        <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-fill-secondary">
            {CONTEXT_CATEGORIES.map((cat) => {
                const value = breakdown[cat.key]
                if (value <= 0) {
                    return null
                }
                return (
                    <div
                        key={cat.key}
                        style={{
                            width: `${(value / denominator) * 100}%`,
                            backgroundColor: cat.color || fallback,
                        }}
                    />
                )
            })}
        </div>
    )
}

function SinglePercentBar({ percentage, color }: { percentage: number; color: string }): JSX.Element {
    return (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-fill-secondary">
            <div className="h-full rounded-full" style={{ width: `${percentage}%`, backgroundColor: color }} />
        </div>
    )
}
