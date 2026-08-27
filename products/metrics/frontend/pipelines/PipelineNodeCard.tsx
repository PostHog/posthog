import { Handle, NodeProps, Position } from '@xyflow/react'

import { PipelineHealthState, PipelineNodeApi, PipelineNodeResultApi, formatStatValue, toHealthState } from './types'

export const HEALTH_COLORS: Record<PipelineHealthState, string> = {
    healthy: 'var(--success)',
    degraded: 'var(--warning)',
    critical: 'var(--danger)',
    no_data: 'var(--muted)',
}

export interface PipelineNodeCardData {
    node: PipelineNodeApi
    result?: PipelineNodeResultApi
    isSelected?: boolean
    onClick?: () => void
    [key: string]: unknown
}

export function PipelineNodeCard({ data }: NodeProps): JSX.Element {
    const { node, result, isSelected, onClick } = data as PipelineNodeCardData
    const state: PipelineHealthState = toHealthState(result?.state ?? 'no_data')
    const accent = HEALTH_COLORS[state]
    const statsById = Object.fromEntries((result?.stats ?? []).map((stat) => [stat.id, stat]))
    const headlineIds = node.headline_stat_ids?.length
        ? node.headline_stat_ids
        : node.stats.slice(0, 3).map((s) => s.id)

    return (
        <>
            <Handle id={`target_${node.id}`} type="target" position={Position.Left} className="opacity-0" />
            <button
                type="button"
                onClick={onClick}
                className={`w-full h-full text-left rounded border bg-surface-primary p-2 transition-shadow cursor-pointer ${
                    isSelected ? 'border-accent shadow-md' : 'border-primary hover:shadow-sm'
                }`}
                style={{ borderLeft: `3px solid ${accent}` }}
                aria-label={`Inspect ${node.name}`}
            >
                <div className="flex items-center gap-1.5">
                    <span className="inline-block w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: accent }} />
                    <span className="font-semibold text-xs truncate">{node.name}</span>
                </div>
                {node.kind ? <div className="text-[10px] text-muted font-mono mb-1 truncate">{node.kind}</div> : null}
                {headlineIds.map((statId) => {
                    const config = node.stats.find((stat) => stat.id === statId)
                    const stat = statsById[statId]
                    if (!config) {
                        return null
                    }
                    return (
                        <div key={statId} className="flex justify-between gap-2 font-mono text-[11px] leading-4">
                            <span className="text-muted truncate">{config.label}</span>
                            <span
                                style={
                                    stat && (stat.state === 'degraded' || stat.state === 'critical')
                                        ? { color: HEALTH_COLORS[toHealthState(stat.state)] }
                                        : undefined
                                }
                            >
                                {stat ? formatStatValue(stat.value, stat.format) : '…'}
                            </span>
                        </div>
                    )
                })}
            </button>
            <Handle id={`source_${node.id}`} type="source" position={Position.Right} className="opacity-0" />
        </>
    )
}

export const PIPELINE_NODE_TYPES = { pipeline: PipelineNodeCard }
