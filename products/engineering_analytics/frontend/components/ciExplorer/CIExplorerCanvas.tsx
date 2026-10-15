import '@xyflow/react/dist/style.css'
import './CIExplorerCanvas.scss'

import {
    type Edge,
    type Node,
    type OnMove,
    Panel,
    ReactFlow,
    ReactFlowProvider,
    type Viewport,
    ViewportPortal,
    useReactFlow,
    useStore,
    useStoreApi,
} from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { type KeyboardEvent, useCallback, useEffect, useMemo, useRef } from 'react'

import { IconArrowLeft, IconMinus, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import {
    CIExplorerWorkflow,
    INNER_SCALE,
    OVERVIEW_MIN_ZOOM,
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
import { CIExplorerDrawer } from './CIExplorerDrawer'
import { CIExplorerLegend } from './CIExplorerLegend'
import { CIExplorerTile } from './CIExplorerTile'
import { CIExplorerTooltip } from './CIExplorerTooltip'

const NO_NODES: Node[] = []
const NO_EDGES: Edge[] = []
// A large workflow is drawn small inside its tile, so reaching one of its shards takes a deep zoom.
const MAX_ZOOM = 400
const MIN_ZOOM = 0.1
const OVERVIEW_ZOOM_FLOOR = 0.5
const BUTTON_ZOOM = 1.6
// Past this zoom a tile's graph is readable, so the tile fades and its jobs become reachable.
const JOBS_ZOOM = 1.8
const CAMERA_MOVE_MS = 280
const BUTTON_ZOOM_MS = 200
const FRAME_PADDING = 40
const RAIL_Y = 52
const RAIL_INSET = 24
const RAIL_BEND = 12
// The room the dock and the back button take from the overview.
const OVERVIEW_MARGIN_X = 48
const OVERVIEW_MARGIN_Y = 128
// A job label is 13px at a zoom of 1. Entering a workflow never shows it smaller than 12px.
const JOB_MIN_ZOOM = 12 / 13
// A job or a shard is framed this wide at most. A tall one pans, so its text keeps its size.
const FRAMED_NODE_WIDTH = 900
const FRAMED_NODE_TOP = 64
const PAN_STEP = 72
// Matches the zoom at which the shard grid starts to fade in, in CIExplorerCanvas.scss.
const SHARDS_SHOWN_ZOOM = 0.4
const LEAVE_ZOOM_RATIO = 0.75
const DRAWER_ROOM = 352
// Below this width the drawer lies over the canvas and takes no room from the camera.
const NARROW_STAGE = 1000

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

/** What the camera frames for a node: a workflow by its graph, a job or a shard by itself. */
function framedElement(node: HTMLElement): { element: HTMLElement; graphScale: number | null } {
    const graph = node.querySelector<HTMLElement>(':scope > [data-graph]')
    return { element: graph ?? node, graphScale: graph ? Number(node.dataset.graphScale) : null }
}

function CIExplorerCanvasContent(): JSX.Element {
    const { workflows, layouts, layoutsLoading, focusedNodeId, focusLevels, activePush, cameraRequest, drawerOpen } =
        useValues(ciExplorerLogic)
    const { setFocus, fitView } = useActions(ciExplorerLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const { setViewport, getViewport } = useReactFlow()
    const store = useStoreApi()
    const stageWidth = useStore((state) => state.width)
    const stageHeight = useStore((state) => state.height)
    const stage = useRef<HTMLDivElement>(null)
    const world = useRef<HTMLDivElement>(null)
    // The zoom each level of the focus was framed at. A zoom out past the midpoint to the level above leaves the level.
    const levelZooms = useRef(new Map<string, number>())
    const handled = useRef<{ sequence: number; stage: string; layout: unknown }>({
        sequence: -1,
        stage: '',
        layout: null,
    })
    // True once the person has moved the camera since the canvas last framed something.
    const movedByPerson = useRef(false)

    const rows = useMemo(
        () => tileRows(workflows.length, stageWidth - OVERVIEW_MARGIN_X, stageHeight - OVERVIEW_MARGIN_Y),
        [workflows.length, stageWidth, stageHeight]
    )
    const tiles = useMemo(() => placeTiles(workflows, rows), [workflows, rows])
    const grid = tileGridSize(Math.ceil(workflows.length / rows), Math.min(rows, workflows.length))
    const rail = useMemo(() => railPaths(workflows.length, rows), [workflows.length, rows])
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const room = stageWidth - (drawerOpen && stageWidth > NARROW_STAGE ? DRAWER_ROOM : 0)

    const fitZoom = Math.min(
        1.1,
        (stageWidth - OVERVIEW_MARGIN_X) / grid.width,
        (stageHeight - OVERVIEW_MARGIN_Y) / grid.height
    )
    const overviewZoom = Math.max(OVERVIEW_MIN_ZOOM, fitZoom)
    const minZoom = Math.max(MIN_ZOOM, Math.min(overviewZoom * OVERVIEW_ZOOM_FLOOR, fitZoom))
    // Each selector returns a boolean, so the canvas renders again only when the camera crosses its threshold.
    const deep = useStore((state) => state.transform[2] >= JOBS_ZOOM)
    const pastOverview = useStore((state) => state.transform[2] > overviewZoom * 1.05)

    const findNode = useCallback(
        (nodeId: string): HTMLElement | null =>
            world.current?.querySelector<HTMLElement>(`[data-node-id="${CSS.escape(nodeId)}"]`) ?? null,
        []
    )

    const overviewCamera = useCallback(
        (fit: boolean): Viewport => {
            const zoom = fit ? Math.max(MIN_ZOOM, fitZoom) : overviewZoom
            return {
                zoom,
                x: Math.max(24, (stageWidth - grid.width * zoom) / 2),
                y: Math.max(24, (stageHeight - 80 - grid.height * zoom) / 2),
            }
        },
        [fitZoom, overviewZoom, stageWidth, stageHeight, grid.width, grid.height]
    )

    const nodeCamera = useCallback(
        (node: HTMLElement, fit: boolean): Viewport | null => {
            const stageElement = stage.current
            const worldElement = world.current
            if (!stageElement || !worldElement) {
                return null
            }
            const { element, graphScale } = framedElement(node)
            const measure = (): { x: number; y: number; width: number; height: number } => {
                const outer = worldElement.getBoundingClientRect()
                // The zoom the page is drawn at now. During a camera move it trails the zoom the store already holds.
                const current = outer.width / worldElement.offsetWidth
                const inner = element.getBoundingClientRect()
                return {
                    x: (inner.left - outer.left) / current,
                    y: (inner.top - outer.top) / current,
                    width: inner.width / current,
                    height: inner.height / current,
                }
            }
            const zoomFor = (box: { width: number; height: number }): number => {
                const fitWidth = (room - 2 * FRAME_PADDING) / box.width
                const fitHeight = (stageHeight - 2 * FRAME_PADDING) / box.height
                if (graphScale !== null) {
                    const fitted = Math.min(1 / graphScale, fitWidth, fitHeight)
                    return fit ? fitted : Math.max(JOB_MIN_ZOOM / graphScale, fitted)
                }
                return fit
                    ? Math.min(fitWidth, fitHeight, MAX_ZOOM)
                    : Math.min(Math.min(room - 2 * FRAME_PADDING, FRAMED_NODE_WIDTH) / box.width, MAX_ZOOM)
            }
            // Titles keep their size on screen, so a node's layout depends on the zoom. The node is measured
            // again as it will be drawn at the zoom the camera is going to.
            const shownZoom = stageElement.style.getPropertyValue('--k')
            stageElement.style.setProperty('--k', String(zoomFor(measure())))
            const box = measure()
            stageElement.style.setProperty('--k', shownZoom)
            const zoom = zoomFor(box)
            const top = graphScale !== null ? FRAME_PADDING : FRAMED_NODE_TOP
            return {
                zoom,
                x: Math.max(FRAME_PADDING, (room - box.width * zoom) / 2) - box.x * zoom,
                y: Math.max(top, (stageHeight - box.height * zoom) / 2) - box.y * zoom,
            }
        },
        [room, stageHeight]
    )

    // The zoom reaches the styles as a custom property, without a render on every frame of a camera move.
    useEffect(() => {
        const showZoom = (zoom: number): void => {
            stage.current?.style.setProperty('--k', String(zoom))
            stage.current?.setAttribute('data-deep', String(zoom >= JOBS_ZOOM))
            // A tile's shards show once they are large enough, which depends on how far its graph was shrunk.
            for (const card of world.current?.querySelectorAll<HTMLElement>('.CIExplorer__card') ?? []) {
                const shown = zoom * Number(card.dataset.graphScale) * INNER_SCALE > SHARDS_SHOWN_ZOOM
                card.setAttribute('data-shards', String(shown))
            }
        }
        showZoom(store.getState().transform[2])
        return store.subscribe((state, previous) => {
            if (state.transform[2] !== previous.transform[2]) {
                showZoom(state.transform[2])
            }
        })
        // A new layout changes how far a tile's graph is shrunk.
    }, [store, layouts])

    // The camera moves when it is asked to, and when the stage changes size. A focus change that came from the
    // camera itself asks for nothing, so a zoom out is never pulled back.
    useEffect(() => {
        // A focus change can resize a node, so the camera waits for the new layout before it frames anything.
        if (!stageWidth || !stageHeight || !world.current || layoutsLoading) {
            return
        }
        const stageKey = `${stageWidth}x${stageHeight}/${room}/${rows}`
        const first = handled.current.sequence === -1
        // A framed node can still grow, for example when its log adds step rows. The frame follows it until
        // the person takes the camera.
        const focusLayout = focusLevels.length ? layouts[focusLevels[0].id] : null
        const regrown = handled.current.layout !== focusLayout && !movedByPerson.current
        if (handled.current.sequence === cameraRequest.sequence && handled.current.stage === stageKey && !regrown) {
            return
        }
        const duration = reducedMotion || first ? 0 : CAMERA_MOVE_MS
        const node = focusedNodeId ? findNode(focusedNodeId) : null
        const workflowPlaced = focusLevels.length > 0 && focusLevels[0].id in layouts
        if (focusedNodeId && !(node && workflowPlaced)) {
            // A node from a link is not drawn until its workflow's jobs are placed. The overview shows until then.
            if (first && handled.current.stage !== stageKey) {
                handled.current = { sequence: -1, stage: stageKey, layout: null }
                void setViewport(overviewCamera(false))
            }
            return
        }
        const camera = node ? nodeCamera(node, cameraRequest.fit) : overviewCamera(cameraRequest.fit)
        if (!camera) {
            return
        }
        levelZooms.current = new Map(
            focusLevels.flatMap((level): [string, number][] => {
                // The focused node was measured for this camera already, unless the camera is a fit.
                if (level.id === focusedNodeId && !cameraRequest.fit) {
                    return [[level.id, camera.zoom]]
                }
                const element = findNode(level.id)
                const zoom = element ? nodeCamera(element, false)?.zoom : undefined
                return zoom === undefined ? [] : [[level.id, zoom]]
            })
        )
        handled.current = { sequence: cameraRequest.sequence, stage: stageKey, layout: focusLayout }
        movedByPerson.current = false
        void setViewport(camera, { duration })
    }, [
        cameraRequest,
        focusedNodeId,
        focusLevels,
        layouts,
        layoutsLoading,
        rows,
        room,
        stageWidth,
        stageHeight,
        reducedMotion,
        findNode,
        nodeCamera,
        overviewCamera,
        setViewport,
    ])

    /** Leaves each level of the focus that the camera has zoomed out of, or panned away from. */
    const followCamera = useCallback(
        (viewport: Viewport): void => {
            movedByPerson.current = true
            if (!stage.current || !focusLevels.length) {
                return
            }
            const bounds = stage.current.getBoundingClientRect()
            const onStage = (nodeId: string): boolean => {
                const node = findNode(nodeId)
                if (!node) {
                    return false
                }
                const seen = framedElement(node).element.getBoundingClientRect()
                return (
                    seen.right > bounds.left &&
                    seen.left < bounds.right &&
                    seen.bottom > bounds.top &&
                    seen.top < bounds.bottom
                )
            }
            let depth = focusLevels.length
            while (depth > 0) {
                const levelZoom = levelZooms.current.get(focusLevels[depth - 1].id) ?? viewport.zoom
                const aboveZoom =
                    depth > 1 ? (levelZooms.current.get(focusLevels[depth - 2].id) ?? overviewZoom) : overviewZoom
                // A shard is framed at almost the zoom of its matrix, so the midpoint alone would leave it on the
                // smallest zoom out. Leaving also takes a clear step back from the level's own zoom.
                const zoomedOut =
                    viewport.zoom <= Math.min(Math.sqrt(levelZoom * aboveZoom), levelZoom * LEAVE_ZOOM_RATIO)
                // This runs on every frame of a gesture. The zoom test is arithmetic, and only a level that
                // passes it pays for a measurement.
                if (!zoomedOut && onStage(focusLevels[depth - 1].id)) {
                    break
                }
                depth--
            }
            if (depth !== focusLevels.length) {
                setFocus(depth ? focusLevels[depth - 1].id : null, false)
            }
        },
        [focusLevels, findNode, overviewZoom, setFocus]
    )

    // React Flow passes the gesture's event, and passes null for a move the canvas made itself.
    const onMove: OnMove = (event, viewport) => {
        if (event) {
            followCamera(viewport)
        }
    }

    const zoomBy = (factor: number): void => {
        const { x, y, zoom } = getViewport()
        const next = Math.max(minZoom, Math.min(MAX_ZOOM, zoom * factor))
        const centerX = room / 2
        const centerY = stageHeight / 2
        const viewport = {
            zoom: next,
            x: centerX - (centerX - x) * (next / zoom),
            y: centerY - (centerY - y) * (next / zoom),
        }
        followCamera(viewport)
        void setViewport(viewport, { duration: reducedMotion ? 0 : BUTTON_ZOOM_MS })
    }

    const zoomOutLevel = (): void => {
        if (focusLevels.length) {
            setFocus(focusLevels[focusLevels.length - 2]?.id ?? null)
        } else {
            void setViewport(overviewCamera(false), { duration: reducedMotion ? 0 : CAMERA_MOVE_MS })
        }
    }

    const onKeyDown = (event: KeyboardEvent): void => {
        // The drawer and the dock keep their own keys.
        if ((event.target as HTMLElement).closest('[data-ci-explorer-controls]') || event.metaKey || event.ctrlKey) {
            return
        }
        if (event.key === 'Escape' && focusLevels.length) {
            zoomOutLevel()
        } else if (event.key === '+' || event.key === '=' || event.key === '-') {
            event.preventDefault()
            zoomBy(event.key === '-' ? 1 / BUTTON_ZOOM : BUTTON_ZOOM)
        } else if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
            event.preventDefault()
            const { x, y, zoom } = getViewport()
            const viewport = {
                zoom,
                x: x + (event.key === 'ArrowLeft' ? PAN_STEP : event.key === 'ArrowRight' ? -PAN_STEP : 0),
                y: y + (event.key === 'ArrowUp' ? PAN_STEP : event.key === 'ArrowDown' ? -PAN_STEP : 0),
            }
            void setViewport(viewport)
            followCamera(viewport)
        }
    }
    const above = focusLevels[focusLevels.length - 2]?.name ?? 'Workflows'

    return (
        // The stage takes the keyboard so the arrow keys can pan it, as a map does.
        // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
        <div
            className="CIExplorer"
            ref={stage}
            onKeyDown={onKeyDown}
            // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
            tabIndex={0}
            role="group"
            aria-label="CI workflows"
            aria-description="Arrow keys pan. Plus and minus zoom. Escape goes back one level."
        >
            <ReactFlow
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                nodes={NO_NODES}
                edges={NO_EDGES}
                minZoom={minZoom}
                maxZoom={MAX_ZOOM}
                // A scroll pans and a pinch zooms, as on a map.
                panOnScroll
                zoomOnDoubleClick={false}
                // The stage handles the arrow keys itself, for a canvas that has no React Flow nodes.
                disableKeyboardA11y
                onMove={onMove}
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
                    <Panel position="top-left" data-ci-explorer-controls>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconArrowLeft />}
                            onClick={zoomOutLevel}
                            aria-label={`Back to ${above}`}
                            data-attr="ci-explorer-zoom-out-level"
                        >
                            {above}
                        </LemonButton>
                    </Panel>
                )}
                <Panel position="top-right" data-ci-explorer-controls>
                    <CIExplorerDrawer maxHeight={Math.max(0, stageHeight - 32)} />
                </Panel>
                <Panel position="bottom-left" className="flex flex-wrap items-center gap-3" data-ci-explorer-controls>
                    <div className="flex gap-1">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconMinus />}
                            aria-label="Zoom out"
                            tooltip="Zoom out"
                            onClick={() => zoomBy(1 / BUTTON_ZOOM)}
                            data-attr="ci-explorer-zoom-out"
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlus />}
                            aria-label="Zoom in"
                            tooltip="Zoom in"
                            onClick={() => zoomBy(BUTTON_ZOOM)}
                            data-attr="ci-explorer-zoom-in"
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            tooltip={focusLevels.length ? 'Fit the selection in view' : 'Fit every workflow in view'}
                            onClick={fitView}
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
