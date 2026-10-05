import '@xyflow/react/dist/style.css'
import './CIExplorerCanvas.scss'

import {
    type Edge,
    type Node,
    Panel,
    ReactFlow,
    ReactFlowProvider,
    ViewportPortal,
    useReactFlow,
    useStore,
    useStoreApi,
} from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { type KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconArrowLeft, IconMinus, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import {
    CIExplorerWorkflow,
    RAIL_LEFT,
    RAIL_TOP,
    TILE_COLUMN_GAP,
    TILE_GAP,
    TILE_HEIGHT,
    TILE_WIDTH,
    tileGridSize,
    tileRows,
} from '../../lib/ciExplorerGraph'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'
import { CIExplorerJobPanel } from './CIExplorerJobPanel'
import { CIExplorerLegend } from './CIExplorerLegend'
import { CIExplorerTile } from './CIExplorerTile'
import { CIExplorerTooltip } from './CIExplorerTooltip'

const NO_NODES: Node[] = []
const NO_EDGES: Edge[] = []
// A large workflow is drawn small inside its tile, so reaching one of its shards takes a deep zoom.
const MAX_ZOOM = 400
const OVERVIEW_ZOOM_FLOOR = 0.5
const BUTTON_ZOOM = 1.6
// Past this zoom a tile's graph is readable, so the tile fades and its jobs become reachable.
const JOBS_ZOOM = 1.8
const CAMERA_MOVE_MS = 550
const FRAME_PADDING = 40
const RAIL_Y = 52
const RAIL_INSET = 24
const RAIL_BEND = 12
// The room the dock and the back button take from the overview.
const OVERVIEW_MARGIN_X = 48
const OVERVIEW_MARGIN_Y = 128
// A tall node is framed by its width down to this many pixels, so its text stays readable.
const MIN_FRAMED_WIDTH = 680

interface PlacedTile {
    workflow: CIExplorerWorkflow
    x: number
    y: number
}

function placeTiles(workflows: CIExplorerWorkflow[], rows: number): PlacedTile[] {
    return workflows.map((workflow, index) => ({
        workflow,
        x: RAIL_LEFT + Math.floor(index / rows) * (TILE_WIDTH + TILE_COLUMN_GAP),
        y: RAIL_TOP + (index % rows) * (TILE_HEIGHT + TILE_GAP),
    }))
}

/** The line that runs along the top and drops down the left of each column to reach every tile. */
function railPaths(count: number, rows: number): { paths: string[]; dots: [number, number][] } {
    const columns = Math.ceil(count / rows)
    const paths: string[] = []
    const dots: [number, number][] = []
    if (columns > 1) {
        paths.push(
            `M8,${RAIL_Y} H${RAIL_LEFT + (columns - 1) * (TILE_WIDTH + TILE_COLUMN_GAP) - RAIL_INSET - RAIL_BEND}`
        )
    }
    for (let column = 0; column < columns; column++) {
        const x = RAIL_LEFT + column * (TILE_WIDTH + TILE_COLUMN_GAP)
        const railX = x - RAIL_INSET
        const inColumn = Math.min(rows, count - column * rows)
        const lastMiddle = RAIL_TOP + (inColumn - 1) * (TILE_HEIGHT + TILE_GAP) + TILE_HEIGHT / 2
        if (column === 0) {
            dots.push([railX, RAIL_Y])
        } else {
            paths.push(`M${railX - RAIL_BEND},${RAIL_Y} Q${railX},${RAIL_Y} ${railX},${RAIL_Y + RAIL_BEND}`)
        }
        paths.push(`M${railX},${column ? RAIL_Y + RAIL_BEND : RAIL_Y} V${lastMiddle - RAIL_BEND}`)
        for (let row = 0; row < inColumn; row++) {
            const middle = RAIL_TOP + row * (TILE_HEIGHT + TILE_GAP) + TILE_HEIGHT / 2
            paths.push(`M${railX},${middle - RAIL_BEND} Q${railX},${middle} ${railX + RAIL_BEND},${middle} H${x}`)
            dots.push([x, middle])
        }
    }
    return { paths, dots }
}

function CIExplorerCanvasContent(): JSX.Element {
    const { workflows, layouts, focusedNodeId, focusLevels, focusedJob, activePush } = useValues(ciExplorerLogic)
    const { setFocus } = useActions(ciExplorerLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const { setViewport, getViewport, zoomTo } = useReactFlow()
    const store = useStoreApi()
    const stageWidth = useStore((state) => state.width)
    const stageHeight = useStore((state) => state.height)
    const stage = useRef<HTMLDivElement>(null)
    const world = useRef<HTMLDivElement>(null)
    const [deep, setDeep] = useState(false)
    const [pastOverview, setPastOverview] = useState(false)

    const rows = useMemo(
        () => tileRows(workflows.length, stageWidth - OVERVIEW_MARGIN_X, stageHeight - OVERVIEW_MARGIN_Y),
        [workflows.length, stageWidth, stageHeight]
    )
    const tiles = useMemo(() => placeTiles(workflows, rows), [workflows, rows])
    const grid = tileGridSize(Math.ceil(workflows.length / rows), Math.min(rows, workflows.length))
    const rail = useMemo(() => railPaths(workflows.length, rows), [workflows.length, rows])
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const overviewZoom = Math.max(
        0.6,
        Math.min(1.1, (stageWidth - OVERVIEW_MARGIN_X) / grid.width, (stageHeight - OVERVIEW_MARGIN_Y) / grid.height)
    )
    const duration = reducedMotion ? 0 : CAMERA_MOVE_MS
    const frameOverview = useCallback(
        (): void =>
            void setViewport(
                {
                    zoom: overviewZoom,
                    x: Math.max(24, (stageWidth - grid.width * overviewZoom) / 2),
                    y: Math.max(24, (stageHeight - 80 - grid.height * overviewZoom) / 2),
                },
                { duration }
            ),
        [setViewport, overviewZoom, stageWidth, stageHeight, grid.width, grid.height, duration]
    )

    // The zoom reaches the styles as a custom property, without a render on every frame of a camera move.
    useEffect(() => {
        const showZoom = (zoom: number): void => {
            stage.current?.style.setProperty('--k', String(zoom))
            stage.current?.setAttribute('data-deep', String(zoom >= JOBS_ZOOM))
            setDeep(zoom >= JOBS_ZOOM)
            setPastOverview(zoom > overviewZoom * 1.05)
        }
        showZoom(store.getState().transform[2])
        return store.subscribe((state, previous) => {
            if (state.transform[2] !== previous.transform[2]) {
                showZoom(state.transform[2])
            }
        })
    }, [store, overviewZoom])

    const layoutsReady = workflows.every((workflow) => workflow.items === null || workflow.id in layouts)

    useEffect(() => {
        if (!stageWidth || !stageHeight || !world.current) {
            return
        }
        const target = focusedNodeId
            ? world.current.querySelector<HTMLElement>(`[data-node-id="${CSS.escape(focusedNodeId)}"]`)
            : null
        if (!target) {
            frameOverview()
            return
        }
        // A workflow is framed by its graph. A shard is the deepest level, so the camera stays on its matrix.
        const graph = target.querySelector<HTMLElement>(':scope > [data-graph]')
        const framed = graph ?? target.closest<HTMLElement>('.CIExplorer__unit') ?? target
        const current = getViewport().zoom
        const outer = world.current.getBoundingClientRect()
        const inner = framed.getBoundingClientRect()
        const box = {
            x: (inner.left - outer.left) / current,
            y: (inner.top - outer.top) / current,
            width: inner.width / current,
            height: inner.height / current,
        }
        const fitWidth = (stageWidth - 2 * FRAME_PADDING) / box.width
        const fitHeight = (stageHeight - 2 * FRAME_PADDING) / box.height
        const zoom = graph
            ? Math.min(1 / Number(target.dataset.graphScale), fitWidth, fitHeight)
            : Math.min(fitWidth, Math.max(fitHeight, MIN_FRAMED_WIDTH / box.width), MAX_ZOOM)
        void setViewport(
            {
                zoom,
                x: (stageWidth - box.width * zoom) / 2 - box.x * zoom,
                y:
                    (graph
                        ? (stageHeight - box.height * zoom) / 2
                        : Math.max(64, (stageHeight - box.height * zoom) / 2)) -
                    box.y * zoom,
            },
            { duration }
        )
        // `layoutsReady` and `rows` are dependencies because both move what the camera frames.
    }, [focusedNodeId, layoutsReady, rows, stageWidth, stageHeight, duration, frameOverview, setViewport, getViewport])

    const zoomOut = (): void => {
        if (focusLevels.length) {
            setFocus(focusLevels[focusLevels.length - 2]?.id ?? null)
        } else {
            frameOverview()
        }
    }
    const onKeyDown = (event: KeyboardEvent): void => {
        if (event.key === 'Escape' && focusLevels.length) {
            zoomOut()
        }
    }
    const above = focusLevels.length ? (focusLevels[focusLevels.length - 2]?.name ?? 'Overview') : 'Zoom out'

    return (
        // eslint-disable-next-line jsx-a11y/no-static-element-interactions
        <div className="CIExplorer" ref={stage} onKeyDown={onKeyDown}>
            <ReactFlow
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                nodes={NO_NODES}
                edges={NO_EDGES}
                // The overview is the outermost level, so a zoom out stops at half its size.
                minZoom={overviewZoom * OVERVIEW_ZOOM_FLOOR}
                maxZoom={MAX_ZOOM}
                // A scroll pans and a pinch zooms, as on a map.
                panOnScroll
                zoomOnDoubleClick={false}
                proOptions={{ hideAttribution: true }}
            >
                <ViewportPortal>
                    {/* eslint-disable-next-line react/forbid-dom-props */}
                    <div className="CIExplorer__world" ref={world} style={{ width: grid.width, height: grid.height }}>
                        <svg className="CIExplorer__rail" aria-hidden="true">
                            {rail.paths.map((d, index) => (
                                <path key={index} d={d} />
                            ))}
                            {rail.dots.map(([cx, cy], index) => (
                                <circle key={index} cx={cx} cy={cy} r={3} />
                            ))}
                        </svg>
                        {activePush && (
                            // eslint-disable-next-line react/forbid-dom-props
                            <div className="CIExplorer__origin" style={{ left: RAIL_LEFT - RAIL_INSET - 8 }}>
                                Commit {activePush.headSha.slice(0, 7)}
                            </div>
                        )}
                        {tiles.map(({ workflow, x, y }) => (
                            <CIExplorerTile
                                key={workflow.id}
                                workflow={workflow}
                                layout={layouts[workflow.id]}
                                x={x}
                                y={y}
                                graphReachable={deep}
                            />
                        ))}
                    </div>
                </ViewportPortal>
                <CIExplorerTooltip stage={stage} />
                {(focusLevels.length > 0 || pastOverview) && (
                    <Panel position="top-left">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconArrowLeft />}
                            onClick={zoomOut}
                            aria-label={focusLevels.length ? `Zoom out to ${above}` : 'Zoom out'}
                            data-attr="ci-explorer-zoom-out-level"
                        >
                            {above}
                        </LemonButton>
                    </Panel>
                )}
                {focusedJob && (
                    <Panel position="top-right">
                        <CIExplorerJobPanel job={focusedJob.job} run={focusedJob.run} />
                    </Panel>
                )}
                <Panel position="bottom-left" className="flex flex-wrap items-center gap-3">
                    <div className="flex gap-1">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconMinus />}
                            aria-label="Zoom out"
                            tooltip="Zoom out"
                            onClick={() => void zoomTo(getViewport().zoom / BUTTON_ZOOM, { duration: 200 })}
                            data-attr="ci-explorer-zoom-out"
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlus />}
                            aria-label="Zoom in"
                            tooltip="Zoom in"
                            onClick={() => void zoomTo(getViewport().zoom * BUTTON_ZOOM, { duration: 200 })}
                            data-attr="ci-explorer-zoom-in"
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            tooltip="Fit everything in view"
                            onClick={() => {
                                setFocus(null)
                                frameOverview()
                            }}
                            data-attr="ci-explorer-fit"
                        >
                            Fit
                        </LemonButton>
                    </div>
                    {deep && <CIExplorerLegend />}
                </Panel>
            </ReactFlow>
        </div>
    )
}

/** One pan and zoom canvas for a push: workflow tiles on a rail, each holding its job graph. */
export function CIExplorerCanvas(): JSX.Element {
    return (
        <ReactFlowProvider>
            <CIExplorerCanvasContent />
        </ReactFlowProvider>
    )
}
