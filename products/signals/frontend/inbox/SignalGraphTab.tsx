import { useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { DetailPanel } from 'scenes/debug/signals/DetailPanel'
import { EdgeTooltip } from 'scenes/debug/signals/EdgeTooltip'
import { buildEdges } from 'scenes/debug/signals/helpers'
import { SignalGraph } from 'scenes/debug/signals/SignalGraph'
import { SimulationControls } from 'scenes/debug/signals/SimulationControls'
import { DEFAULT_CONFIG, GraphEdge, SignalNode, SimConfig } from 'scenes/debug/signals/types'
import { useD3ForceSimulation } from 'scenes/debug/signals/useD3ForceSimulation'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

const STORAGE_KEY = 'inbox-signal-graph-physics'

function loadConfig(): SimConfig {
    try {
        const stored = localStorage.getItem(STORAGE_KEY)
        if (stored) {
            return { ...DEFAULT_CONFIG, ...JSON.parse(stored) }
        }
    } catch {
        // ignore
    }
    return { ...DEFAULT_CONFIG }
}

export function SignalGraphTab({ signals }: { signals: SignalNode[] }): JSX.Element {
    const { isDev } = useValues(preflightLogic)
    const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null)
    const [hoveredEdge, setHoveredEdge] = useState<GraphEdge | null>(null)
    const [mousePos, setMousePos] = useState({ x: 0, y: 0 })
    const [simConfig, setSimConfig] = useState<SimConfig>(loadConfig)

    const handleConfigChange = (config: SimConfig): void => {
        setSimConfig(config)
        localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
    }

    const {
        positions,
        edges,
        containerRef,
        onNodeDragStart,
        draggedNodeId,
        didDragRef,
        transform,
        viewportCenter,
        resetView,
    } = useD3ForceSimulation(signals, simConfig, {
        initialScale: signals.length > 16 ? 0.5 : signals.length > 4 ? 0.75 : 1.0,
    })

    const allEdges = useMemo(() => buildEdges(signals), [signals])
    const rootIds = useMemo(() => {
        const childIds = new Set(allEdges.map((e) => e.target))
        return new Set(signals.filter((s) => !childIds.has(s.signal_id)).map((s) => s.signal_id))
    }, [signals, allEdges])

    const selectedSignal = useMemo(
        () => signals.find((s) => s.signal_id === selectedSignalId) ?? null,
        [signals, selectedSignalId]
    )

    const handleMouseMove = useRef((e: React.MouseEvent): void => {
        setMousePos({ x: e.clientX, y: e.clientY })
    }).current

    return (
        <div className="relative w-full h-full">
            <SignalGraph
                signals={signals}
                positions={positions}
                edges={edges}
                selectedSignalId={selectedSignalId}
                onSelectSignal={setSelectedSignalId}
                hoveredEdge={hoveredEdge}
                onHoverEdge={setHoveredEdge}
                onMouseMove={handleMouseMove}
                containerRef={containerRef}
                onNodeDragStart={onNodeDragStart}
                draggedNodeId={draggedNodeId}
                didDragRef={didDragRef}
                transform={transform}
            />
            {selectedSignal && (
                <DetailPanel
                    signal={selectedSignal}
                    isRoot={rootIds.has(selectedSignal.signal_id)}
                    onClose={() => setSelectedSignalId(null)}
                />
            )}
            {hoveredEdge && <EdgeTooltip edge={hoveredEdge} x={mousePos.x} y={mousePos.y} />}
            {/* Zoom level & viewport center indicator */}
            <div className="absolute bottom-3 left-3 z-20 flex items-center gap-0.5 rounded-md border border-border bg-surface-primary h-8 px-0.5 text-xs text-muted font-mono tabular-nums select-none">
                <span className="ml-1">{Math.round(transform.k * 100)}%</span>
                <span className="mx-2 opacity-50">•</span>
                <span>
                    X: {viewportCenter.x}, Y: {viewportCenter.y}
                </span>
                <LemonButton size="xsmall" type="tertiary" onClick={resetView} className="ml-1">
                    Reset
                </LemonButton>
            </div>
            {isDev && <SimulationControls config={simConfig} onChange={handleConfigChange} />}
        </div>
    )
}
