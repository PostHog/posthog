import { useValues } from 'kea'
import { useMemo } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { shareLevels, totalComputeSeconds } from '../../lib/ciExplorerDetails'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'

// Each deeper level is a darker bar nested inside the level around it.
const LEVEL_CLASS = [
    'bg-[color-mix(in_oklab,var(--color-text-primary)_30%,var(--color-bg-surface-primary))]',
    'bg-[color-mix(in_oklab,var(--color-text-primary)_58%,var(--color-bg-surface-primary))]',
    'bg-[var(--color-text-primary)]',
]
const LEVEL_INSET_PX = 3

/** How much of the push's CI time the current zoom level accounts for. */
export function CIExplorerShare(): JSX.Element {
    const { workflows, focusedNodeId } = useValues(ciExplorerLogic)
    const total = useMemo(() => totalComputeSeconds(workflows), [workflows])
    const levels = useMemo(() => shareLevels(workflows, focusedNodeId), [workflows, focusedNodeId])

    return (
        <section aria-label="Share of CI time" className="flex flex-col gap-2">
            <div className="flex items-center gap-3">
                <Tooltip title={`All jobs of this push add up to ${humanFriendlyDuration(total)}`}>
                    <div className="relative h-5 flex-1 overflow-hidden rounded bg-fill-secondary">
                        {levels.map((level, index) => (
                            <i
                                key={level.id}
                                className={cn(
                                    'absolute min-w-1 rounded-sm transition-[width] duration-300 motion-reduce:transition-none',
                                    LEVEL_CLASS[index]
                                )}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    inset: `${index * LEVEL_INSET_PX}px auto ${index * LEVEL_INSET_PX}px ${index * LEVEL_INSET_PX}px`,
                                    width: `calc(${level.share}% - ${index * LEVEL_INSET_PX * 2}px)`,
                                }}
                            />
                        ))}
                    </div>
                </Tooltip>
                <span className="font-mono text-xs text-secondary whitespace-nowrap">
                    {humanFriendlyDuration(total, { maxUnits: 2 })}
                </span>
            </div>
            <div className="flex min-h-5 flex-wrap gap-x-5 gap-y-1 text-xs text-secondary">
                {levels.map((level, index) => (
                    <Tooltip
                        key={level.id}
                        title={`${humanFriendlyDuration(level.computeSeconds)} of CI time${
                            level.wallSeconds === null
                                ? ''
                                : `, ${humanFriendlyDuration(level.wallSeconds)} start to finish`
                        }`}
                    >
                        <span className="inline-flex items-center gap-1.5">
                            <i className={cn('size-2 rounded-sm', LEVEL_CLASS[index])} />
                            {level.name}
                            <b className="font-semibold text-primary">
                                {level.share < 1 ? '<1' : Math.round(level.share)}%
                            </b>
                        </span>
                    </Tooltip>
                ))}
            </div>
        </section>
    )
}
