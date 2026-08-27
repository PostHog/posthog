import { Link } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { HEALTH_COLORS } from './PipelineNodeCard'
import {
    PipelineBreakdownRowApi,
    PipelineConfigApi,
    PipelineEdgeResultApi,
    PipelineEvaluationApi,
    PipelineHealthState,
    PipelineStatResultApi,
    formatStatValue,
    toHealthState,
} from './types'

const STATE_TAG: Record<PipelineHealthState, 'success' | 'warning' | 'danger' | 'muted'> = {
    healthy: 'success',
    degraded: 'warning',
    critical: 'danger',
    no_data: 'muted',
}

function Sparkline({ points }: { points: { value: number | null }[] }): JSX.Element | null {
    const values = points.map((p) => p.value).filter((v): v is number => v !== null)
    if (values.length < 2) {
        return null
    }
    const width = 160
    const height = 32
    const min = Math.min(...values)
    const range = Math.max(...values) - min || 1
    const coords = values
        .map((value, index) => {
            const x = (index * (width - 4)) / (values.length - 1) + 2
            const y = height - 2 - ((value - min) / range) * (height - 4)
            return `${x.toFixed(1)},${y.toFixed(1)}`
        })
        .join(' ')
    return (
        <svg width={width} height={height} className="mt-2" aria-hidden="true">
            <polyline points={coords} fill="none" stroke="var(--accent)" strokeWidth={1.5} strokeLinejoin="round" />
        </svg>
    )
}

function StatCard({ stat }: { stat: PipelineStatResultApi }): JSX.Element {
    return (
        <div className="border rounded p-2 bg-surface-primary">
            <div
                className="font-mono text-base font-semibold"
                style={{ color: HEALTH_COLORS[toHealthState(stat.state)] }}
            >
                {formatStatValue(stat.value, stat.format)}
            </div>
            <div className="text-[10px] uppercase tracking-wide text-muted mt-0.5">{stat.label}</div>
        </div>
    )
}

function BreakdownTable({
    rows,
    others,
    groupByKey,
}: {
    rows: PipelineBreakdownRowApi[]
    others: PipelineBreakdownRowApi | null
    groupByKey: string
}): JSX.Element {
    const allRows = others ? [...rows, others] : rows
    return (
        <LemonTable
            size="small"
            columns={[
                { title: groupByKey, dataIndex: 'label' },
                { title: 'value', render: (_, row) => formatStatValue(row.value, 'count') },
            ]}
            dataSource={allRows}
            rowKey="label"
        />
    )
}

export interface PipelineDrillPanelProps {
    config: PipelineConfigApi
    evaluation: PipelineEvaluationApi | null
    selectedNodeId: string | null
    selectedEdgeKey: string | null
}

export function PipelineDrillPanel({
    config,
    evaluation,
    selectedNodeId,
    selectedEdgeKey,
}: PipelineDrillPanelProps): JSX.Element {
    if (selectedNodeId) {
        const node = config.nodes.find((n) => n.id === selectedNodeId)
        const result = evaluation?.nodes.find((n) => n.id === selectedNodeId)
        if (!node) {
            return <></>
        }
        return (
            <div className="border rounded p-3 bg-surface-primary">
                <div className="flex items-center gap-2 border-b pb-2 mb-3">
                    <span
                        className="inline-block w-2.5 h-2.5 rounded-full"
                        style={{ backgroundColor: HEALTH_COLORS[toHealthState(result?.state ?? 'no_data')] }}
                    />
                    <span className="font-semibold">{node.name}</span>
                    <span className="font-mono text-xs text-muted">{node.kind}</span>
                    {result ? <LemonTag type={STATE_TAG[toHealthState(result.state)]}>{result.state}</LemonTag> : null}
                </div>
                <div className="grid gap-2 grid-cols-2 md:grid-cols-4">
                    {(result?.stats ?? []).map((stat) => (
                        <StatCard key={stat.id} stat={stat} />
                    ))}
                </div>
                {(result?.stats ?? [])
                    .filter((stat) => stat.breakdown_rows.length > 0)
                    .map((stat) => {
                        const statConfig = node.stats.find((s) => s.id === stat.id)
                        return (
                            <div key={stat.id} className="mt-3">
                                <div className="text-xs text-muted uppercase tracking-wide mb-1">
                                    {stat.label} — breakdown
                                </div>
                                <BreakdownTable
                                    rows={stat.breakdown_rows}
                                    others={stat.breakdown_others}
                                    groupByKey={statConfig?.breakdown?.group_by_key ?? 'label'}
                                />
                            </div>
                        )
                    })}
                {node.note ? <div className="mt-3 text-xs text-muted border-l-2 pl-2">{node.note}</div> : null}
                {node.links?.length ? (
                    <div className="flex gap-2 flex-wrap mt-3">
                        {node.links.map((link) => (
                            <Link key={link.url} to={link.url} target="_blank" className="text-xs">
                                {link.label} ↗
                            </Link>
                        ))}
                    </div>
                ) : null}
            </div>
        )
    }

    if (selectedEdgeKey) {
        const edgeResult: PipelineEdgeResultApi | undefined = evaluation?.edges.find(
            (edge) => `${edge.source}>${edge.target}` === selectedEdgeKey
        )
        const [source, target] = selectedEdgeKey.split('>')
        const sourceName = config.nodes.find((n) => n.id === source)?.name ?? source
        const targetName = config.nodes.find((n) => n.id === target)?.name ?? target
        return (
            <div className="border rounded p-3 bg-surface-primary">
                <div className="flex items-center gap-2 border-b pb-2 mb-3">
                    <span className="font-semibold">
                        {sourceName} → {targetName}
                    </span>
                    {edgeResult?.hot ? <LemonTag type="warning">hot</LemonTag> : null}
                </div>
                {edgeResult ? (
                    <div className="grid gap-2 grid-cols-2 md:grid-cols-3">
                        <div className="border rounded p-2">
                            <div className="font-mono text-base font-semibold">
                                {formatStatValue(edgeResult.current_value, 'rate')}
                            </div>
                            <div className="text-[10px] uppercase text-muted mt-0.5">current</div>
                        </div>
                        <div className="border rounded p-2">
                            <div className="font-mono text-base font-semibold">
                                {formatStatValue(edgeResult.baseline_value, 'rate')}
                            </div>
                            <div className="text-[10px] uppercase text-muted mt-0.5">baseline</div>
                        </div>
                        <div className="border rounded p-2">
                            <div className="font-mono text-base font-semibold">
                                {edgeResult.multiplier === null ? 'new' : `${edgeResult.multiplier.toFixed(1)}×`}
                            </div>
                            <div className="text-[10px] uppercase text-muted mt-0.5">vs baseline</div>
                        </div>
                    </div>
                ) : (
                    <div className="text-muted text-sm">No evaluation yet.</div>
                )}
                {edgeResult ? <Sparkline points={edgeResult.points} /> : null}
            </div>
        )
    }

    return (
        <div className="border rounded p-3 bg-surface-primary text-sm text-muted">
            Click a node to see its stats and breakdowns, or an edge for throughput vs baseline.
        </div>
    )
}
