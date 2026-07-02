import { ReactNode } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface DistributionSegment {
    key: string
    label: ReactNode
    value: number
    /** Any CSS color (e.g. a `getSeriesColor(i)` result). */
    color: string
    /** Extra tooltip line under the label (e.g. the formatted amount). */
    caption?: ReactNode
}

/**
 * One horizontal bar split into colored segments sized by share of the total (cost by runner tier, jobs
 * by status, …), each hover-able for its share. Segments under 0.5% are dropped as noise.
 */
export function DistributionBar({
    segments,
    className,
}: {
    segments: DistributionSegment[]
    className?: string
}): JSX.Element | null {
    const total = segments.reduce((sum, seg) => sum + Math.max(0, seg.value), 0)
    if (total <= 0) {
        return null
    }
    return (
        <div className={cn('flex h-2.5 w-full overflow-hidden rounded-sm bg-border-light', className)}>
            {segments.map((seg) => {
                const percent = (Math.max(0, seg.value) / total) * 100
                if (percent < 0.5) {
                    return null
                }
                return (
                    <Tooltip
                        key={seg.key}
                        title={
                            <div className="text-xs">
                                <div className="font-semibold">{seg.label}</div>
                                <div>
                                    {seg.caption != null && <>{seg.caption} · </>}
                                    {Math.round(percent)}%
                                </div>
                            </div>
                        }
                    >
                        {/* eslint-disable-next-line react/forbid-dom-props */}
                        <div
                            className="h-full transition-all hover:opacity-80"
                            style={{ width: `${percent}%`, backgroundColor: seg.color }}
                        />
                    </Tooltip>
                )
            })}
        </div>
    )
}
