import { useActions, useValues } from 'kea'
import type { CSSProperties } from 'react'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { CIExplorerLayout, CIExplorerWorkflow, TILE_WIDTH } from '../../lib/ciExplorerGraph'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'
import { CIExplorerUnit } from './CIExplorerUnit'

const TILE_PADDING = 17
const GRAPH_TOP = 53
// The room a tile has for its graph. A graph never shows larger than the cap, so a small workflow keeps its scale.
const GRAPH_WIDTH = TILE_WIDTH - 34
const GRAPH_HEIGHT = 28
const GRAPH_MAX_SCALE = 0.45

/** A workflow run: a name, a duration bar, and its job graph drawn small enough to fit inside. */
export function CIExplorerTile({
    workflow,
    layout,
    x,
    y,
    graphReachable,
}: {
    workflow: CIExplorerWorkflow
    layout: CIExplorerLayout | undefined
    x: number
    y: number
    /** False while the graph is too small to read, which keeps its nodes out of the tab order. */
    graphReachable: boolean
}): JSX.Element {
    const { setFocus } = useActions(ciExplorerLogic)
    const { focusedNodeId } = useValues(ciExplorerLogic)
    const { run, status } = workflow
    const scale = layout
        ? Math.min(GRAPH_MAX_SCALE, GRAPH_WIDTH / layout.width, GRAPH_HEIGHT / layout.height)
        : GRAPH_MAX_SCALE

    return (
        <section
            className={cn('CIExplorer__card', status === 'failure' && 'CIExplorer__card--failure')}
            data-node-id={workflow.id}
            data-graph-scale={scale}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ left: x, top: y, '--s': scale } as CSSProperties}
        >
            <button
                type="button"
                className="CIExplorer__cardButton"
                aria-label={`${run.workflow}, zoom in`}
                aria-pressed={focusedNodeId === workflow.id}
                onClick={() => setFocus(workflow.id)}
                data-attr="ci-explorer-workflow"
            >
                <span className="CIExplorer__cardHeader">
                    <i className={`CIExplorer__dot CIExplorer__dot--${status}`} />
                    <b>{run.workflow}</b>
                    <span className="CIExplorer__duration">
                        {run.durationSeconds === null
                            ? 'Running'
                            : humanFriendlyDuration(run.durationSeconds, { maxUnits: 2 })}
                    </span>
                </span>
                <span className="CIExplorer__cardBar">
                    {/* eslint-disable-next-line react/forbid-dom-props */}
                    <i style={{ width: `${Math.max(1, workflow.durationShare * 100)}%` }} />
                </span>
            </button>
            {layout && workflow.items && (
                <div
                    className="CIExplorer__graph"
                    data-graph
                    // React 18 types lack the attribute.
                    {...(graphReachable ? {} : { inert: '' })}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        width: layout.width,
                        height: layout.height,
                        left: TILE_PADDING + (GRAPH_WIDTH - layout.width * scale) / 2,
                        top: GRAPH_TOP + (GRAPH_HEIGHT - layout.height * scale) / 2,
                        transform: `scale(${scale})`,
                    }}
                >
                    <svg aria-hidden="true">
                        {layout.wires.map((d, index) => (
                            <path key={index} d={d} />
                        ))}
                        {layout.ends.map((end, index) => (
                            <circle key={index} cx={end.x} cy={end.y} r={3} />
                        ))}
                    </svg>
                    {workflow.items.map((item) => (
                        <CIExplorerUnit
                            key={item.id}
                            item={item}
                            x={layout.at[item.id]?.x ?? 0}
                            y={layout.at[item.id]?.y ?? 0}
                        />
                    ))}
                </div>
            )}
        </section>
    )
}
