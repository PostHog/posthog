import { useActions, useValues } from 'kea'
import type { CSSProperties, MouseEvent } from 'react'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { CIExplorerItem, INNER_SCALE, NODE_WIDTH, itemSize } from '../../lib/ciExplorerGraph'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'
import { clickedNodeId } from './ciExplorerFocus'

function duration(seconds: number | null): string {
    return seconds === null ? '' : humanFriendlyDuration(seconds, { maxUnits: 2 })
}

/** One node of a workflow's graph: a job, or a matrix job with its shards inside it. */
export function CIExplorerUnit({ item, x, y }: { item: CIExplorerItem; x: number; y: number }): JSX.Element {
    const { focusedNodeId } = useValues(ciExplorerLogic)
    const { setFocus } = useActions(ciExplorerLogic)
    const { titleHeight, gridHeight } = itemSize(item)
    const focus = (event: MouseEvent<HTMLElement>): void => setFocus(clickedNodeId(event.currentTarget))

    return (
        <div
            className={cn(
                'CIExplorer__unit',
                `CIExplorer__unit--${item.kind}`,
                item.status === 'failure' && 'CIExplorer__unit--failure',
                focusedNodeId === item.id && 'CIExplorer__unit--focus'
            )}
            data-node-id={item.id}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ left: x, top: y, width: NODE_WIDTH }}
        >
            {item.shards.length > 0 && <i className="CIExplorer__stack" aria-hidden="true" />}
            <button
                type="button"
                className="CIExplorer__job"
                aria-pressed={focusedNodeId === item.id}
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
            {item.shards.length > 0 && (
                // eslint-disable-next-line react/forbid-dom-props
                <div className="CIExplorer__cells" style={{ height: gridHeight }}>
                    {/* eslint-disable-next-line react/forbid-dom-props */}
                    <div className="CIExplorer__cellGrid" style={{ transform: `scale(${INNER_SCALE})` }}>
                        {item.shards.map((shard) => (
                            <button
                                key={shard.id}
                                type="button"
                                className={cn(
                                    'CIExplorer__cell',
                                    shard.status === 'failure' && 'CIExplorer__cell--failure'
                                )}
                                data-node-id={shard.id}
                                aria-pressed={focusedNodeId === shard.id}
                                onClick={focus}
                                data-attr="ci-explorer-shard"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ '--w': shard.durationShare } as CSSProperties}
                            >
                                <i className={`CIExplorer__dot CIExplorer__dot--${shard.status}`} />
                                <span className="CIExplorer__cellName">{shard.label}</span>
                                <span className="CIExplorer__duration">{duration(shard.job.duration_seconds)}</span>
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
