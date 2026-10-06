import { useActions, useValues } from 'kea'
import type { CSSProperties, MouseEvent } from 'react'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { statusLabel } from '../../lib/ciExplorerDetails'
import { CIExplorerItem, CIStatus, INNER_SCALE, NODE_WIDTH, itemSize, shownSteps } from '../../lib/ciExplorerGraph'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'
import { clickedNodeId } from './ciExplorerFocus'
import { CIExplorerSteps } from './CIExplorerSteps'

// A matrix has one status for many jobs, so its neutral status covers cancelled and skipped shards alike.
const ITEM_STATUS: Record<CIStatus, string> = {
    success: 'Passed',
    failure: 'Failed',
    running: 'Running',
    neutral: 'No verdict',
}

function duration(seconds: number | null): string {
    return seconds === null ? '' : humanFriendlyDuration(seconds, { maxUnits: 2 })
}

/** One node of a workflow's graph: a job, or a matrix job with its shards inside it. A focused job lists its steps. */
export function CIExplorerUnit({ item, x, y }: { item: CIExplorerItem; x: number; y: number }): JSX.Element {
    const { focusedNodeId, focusedBadgedSteps } = useValues(ciExplorerLogic)
    const { setFocus } = useActions(ciExplorerLogic)
    const { titleHeight, gridHeight, stepsHeight } = itemSize(item, focusedNodeId, focusedBadgedSteps)
    const focus = (event: MouseEvent<HTMLElement>): void => setFocus(clickedNodeId(event.currentTarget))
    const focused = focusedNodeId === item.id

    return (
        <div
            className={cn(
                'CIExplorer__unit',
                `CIExplorer__unit--${item.kind}`,
                item.status === 'failure' && 'CIExplorer__unit--failure',
                focused && 'CIExplorer__unit--focus'
            )}
            data-node-id={item.id}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ left: x, top: y, width: NODE_WIDTH }}
        >
            {item.shards.length > 0 && <i className="CIExplorer__stack" aria-hidden="true" />}
            <button
                type="button"
                className="CIExplorer__job"
                aria-label={`${item.name}, ${ITEM_STATUS[item.status]}`}
                aria-pressed={focused}
                onClick={focus}
                data-attr="ci-explorer-job"
            >
                <span
                    className="CIExplorer__jobTitle"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ '--th': `${titleHeight}px` } as CSSProperties}
                >
                    <i className={`CIExplorer__dot CIExplorer__dot--${item.status}`} />
                    <span className="CIExplorer__jobName">
                        {item.name}
                        {item.shards.length > 0 && ` ×${item.shards.length}`}
                    </span>
                    <span className="CIExplorer__duration">{duration(item.durationSeconds)}</span>
                </span>
                <span className="CIExplorer__meter">
                    {/* eslint-disable-next-line react/forbid-dom-props */}
                    <i style={{ width: `${Math.max(2, item.durationShare * 100)}%` }} />
                </span>
            </button>
            {item.job &&
                stepsHeight > 0 && (
                    // eslint-disable-next-line react/forbid-dom-props
                    <div className="CIExplorer__cells CIExplorer__cells--steps" style={{ height: stepsHeight }}>
                        {/* eslint-disable-next-line react/forbid-dom-props */}
                        <div className="CIExplorer__scaled" style={{ transform: `scale(${INNER_SCALE})` }}>
                            <CIExplorerSteps job={item.job} />
                        </div>
                    </div>
                )}
            {item.shards.length > 0 && (
                // eslint-disable-next-line react/forbid-dom-props
                <div className="CIExplorer__cells" style={{ height: gridHeight }}>
                    {/* eslint-disable-next-line react/forbid-dom-props */}
                    <div className="CIExplorer__cellGrid" style={{ transform: `scale(${INNER_SCALE})` }}>
                        {item.shards.map((shard) => {
                            const shardFocused = focusedNodeId === shard.id
                            return (
                                <div
                                    key={shard.id}
                                    className={cn(
                                        'CIExplorer__cell',
                                        shard.status === 'failure' && 'CIExplorer__cell--failure',
                                        shardFocused && 'CIExplorer__cell--focus'
                                    )}
                                    data-node-id={shard.id}
                                >
                                    <button
                                        type="button"
                                        className="CIExplorer__cellHead"
                                        aria-label={`${shard.job.name}, ${statusLabel(shard.job.conclusion)}`}
                                        aria-pressed={shardFocused}
                                        onClick={focus}
                                        data-attr="ci-explorer-shard"
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{ '--w': shard.durationShare } as CSSProperties}
                                    >
                                        <i className={`CIExplorer__dot CIExplorer__dot--${shard.status}`} />
                                        <span className="CIExplorer__cellName">{shard.label}</span>
                                        <span className="CIExplorer__duration">
                                            {duration(shard.job.duration_seconds)}
                                        </span>
                                    </button>
                                    {shardFocused && shownSteps(shard.job, focusedBadgedSteps).length > 0 && (
                                        <div className="CIExplorer__cellSteps">
                                            <CIExplorerSteps job={shard.job} />
                                        </div>
                                    )}
                                </div>
                            )
                        })}
                    </div>
                </div>
            )}
        </div>
    )
}
