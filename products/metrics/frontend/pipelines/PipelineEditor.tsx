import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import {
    emptyEdge,
    emptyNode,
    emptyStat,
    emptyVariable,
    removeEdge,
    removeNode,
    removeStat,
    removeVariable,
    updateEdge,
    updateNode,
    updateStat,
    updateVariable,
} from './configEdits'
import { PipelineLogicProps, pipelineLogic } from './pipelineLogic'
import { PipelineConfigType, PipelineStatFormat } from './types'

const AGGREGATION_OPTIONS = ['sum', 'avg', 'count', 'rate', 'increase', 'quantile', 'histogram_quantile'].map(
    (value) => ({ value, label: value })
)
const FORMAT_OPTIONS = ['count', 'rate', 'bytes', 'pct', 'duration'].map((value) => ({ value, label: value }))

export function PipelineEditor({ id }: PipelineLogicProps): JSX.Element {
    const logic = pipelineLogic({ id })
    const { draft } = useValues(logic)
    const { setDraft } = useActions(logic)

    if (!draft) {
        return <></>
    }
    const config = draft.config
    const setConfig = (next: PipelineConfigType): void => setDraft({ ...draft, config: next })
    const nodeOptions = config.nodes.map((node) => ({ value: node.id, label: node.name || node.id }))

    return (
        <div className="deprecated-space-y-4 max-w-3xl">
            <div className="deprecated-space-y-2">
                <LemonLabel>Name</LemonLabel>
                <LemonInput
                    value={draft.name}
                    onChange={(name) => setDraft({ ...draft, name })}
                    placeholder="Logs ingestion pipeline"
                    data-attr="pipeline-editor-name"
                />
                <LemonLabel>Description</LemonLabel>
                <LemonTextArea
                    value={draft.description}
                    onChange={(description) => setDraft({ ...draft, description })}
                    placeholder="What this pipeline observes and who owns it"
                />
            </div>

            <div>
                <div className="flex items-center justify-between mb-2">
                    <h3 className="mb-0">Nodes</h3>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={() => setConfig({ ...config, nodes: [...config.nodes, emptyNode(config)] })}
                        data-attr="pipeline-editor-add-node"
                    >
                        Add node
                    </LemonButton>
                </div>
                <LemonCollapse
                    multiple
                    panels={config.nodes.map((node, nodeIndex) => ({
                        // Keyed by position, not node id: editing the id must
                        // not remount (and collapse) the open panel.
                        key: `node-${nodeIndex}`,
                        header: node.name || node.id,
                        content: (
                            <div className="deprecated-space-y-2">
                                <div className="grid grid-cols-3 gap-2">
                                    <div>
                                        <LemonLabel>Id</LemonLabel>
                                        <LemonInput
                                            value={node.id}
                                            onChange={(value) =>
                                                setConfig(updateNode(config, nodeIndex, { id: value }))
                                            }
                                        />
                                    </div>
                                    <div>
                                        <LemonLabel>Name</LemonLabel>
                                        <LemonInput
                                            value={node.name}
                                            onChange={(value) =>
                                                setConfig(updateNode(config, nodeIndex, { name: value }))
                                            }
                                        />
                                    </div>
                                    <div>
                                        <LemonLabel>Kind</LemonLabel>
                                        <LemonInput
                                            value={node.kind ?? ''}
                                            onChange={(value) =>
                                                setConfig(updateNode(config, nodeIndex, { kind: value }))
                                            }
                                            placeholder="e.g. WarpStream BYOC"
                                        />
                                    </div>
                                </div>
                                {node.stats.map((stat, statIndex) => (
                                    <div key={statIndex} className="border rounded p-2 deprecated-space-y-2">
                                        <div className="grid grid-cols-3 gap-2">
                                            <div>
                                                <LemonLabel>Stat id</LemonLabel>
                                                <LemonInput
                                                    value={stat.id}
                                                    onChange={(value) =>
                                                        setConfig(
                                                            updateStat(config, nodeIndex, statIndex, { id: value })
                                                        )
                                                    }
                                                />
                                            </div>
                                            <div>
                                                <LemonLabel>Label</LemonLabel>
                                                <LemonInput
                                                    value={stat.label}
                                                    onChange={(value) =>
                                                        setConfig(
                                                            updateStat(config, nodeIndex, statIndex, { label: value })
                                                        )
                                                    }
                                                />
                                            </div>
                                            <div>
                                                <LemonLabel>Metric</LemonLabel>
                                                <LemonInput
                                                    value={stat.metric_name}
                                                    onChange={(value) =>
                                                        setConfig(
                                                            updateStat(config, nodeIndex, statIndex, {
                                                                metric_name: value,
                                                            })
                                                        )
                                                    }
                                                    placeholder="exact ingested metric name"
                                                />
                                            </div>
                                        </div>
                                        <div className="grid grid-cols-4 gap-2 items-end">
                                            <div>
                                                <LemonLabel>Aggregation</LemonLabel>
                                                <LemonSelect
                                                    value={stat.aggregation ?? 'sum'}
                                                    options={AGGREGATION_OPTIONS}
                                                    onChange={(value) =>
                                                        setConfig(
                                                            updateStat(config, nodeIndex, statIndex, {
                                                                aggregation: value,
                                                            })
                                                        )
                                                    }
                                                />
                                            </div>
                                            <div>
                                                <LemonLabel>Format</LemonLabel>
                                                <LemonSelect
                                                    value={stat.format ?? 'count'}
                                                    options={FORMAT_OPTIONS}
                                                    onChange={(value) =>
                                                        setConfig(
                                                            updateStat(config, nodeIndex, statIndex, {
                                                                format: value as PipelineStatFormat,
                                                            })
                                                        )
                                                    }
                                                />
                                            </div>
                                            <div>
                                                <LemonLabel>Warn above</LemonLabel>
                                                <LemonInput
                                                    type="number"
                                                    value={stat.thresholds?.warn?.upper ?? undefined}
                                                    onChange={(value) =>
                                                        setConfig(
                                                            updateStat(config, nodeIndex, statIndex, {
                                                                thresholds: {
                                                                    ...stat.thresholds,
                                                                    warn: value === undefined ? null : { upper: value },
                                                                },
                                                            })
                                                        )
                                                    }
                                                />
                                            </div>
                                            <div>
                                                <LemonLabel>Critical above</LemonLabel>
                                                <LemonInput
                                                    type="number"
                                                    value={stat.thresholds?.crit?.upper ?? undefined}
                                                    onChange={(value) =>
                                                        setConfig(
                                                            updateStat(config, nodeIndex, statIndex, {
                                                                thresholds: {
                                                                    ...stat.thresholds,
                                                                    crit: value === undefined ? null : { upper: value },
                                                                },
                                                            })
                                                        )
                                                    }
                                                />
                                            </div>
                                        </div>
                                        <LemonButton
                                            size="xsmall"
                                            status="danger"
                                            icon={<IconTrash />}
                                            onClick={() => setConfig(removeStat(config, nodeIndex, statIndex))}
                                        >
                                            Remove stat
                                        </LemonButton>
                                    </div>
                                ))}
                                <div className="flex gap-2">
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconPlus />}
                                        onClick={() =>
                                            setConfig(
                                                updateNode(config, nodeIndex, {
                                                    stats: [...node.stats, emptyStat(node)],
                                                })
                                            )
                                        }
                                    >
                                        Add stat
                                    </LemonButton>
                                    <LemonButton
                                        size="small"
                                        status="danger"
                                        icon={<IconTrash />}
                                        onClick={() => setConfig(removeNode(config, nodeIndex))}
                                    >
                                        Remove node
                                    </LemonButton>
                                </div>
                            </div>
                        ),
                    }))}
                />
            </div>

            <div>
                <div className="flex items-center justify-between mb-2">
                    <h3 className="mb-0">Edges</h3>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        disabledReason={config.nodes.length < 2 ? 'Add at least two nodes first' : undefined}
                        onClick={() => {
                            const edge = emptyEdge(config)
                            if (edge) {
                                setConfig({ ...config, edges: [...config.edges, edge] })
                            }
                        }}
                        data-attr="pipeline-editor-add-edge"
                    >
                        Add edge
                    </LemonButton>
                </div>
                {config.edges.map((edge, edgeIndex) => (
                    <div key={edgeIndex} className="border rounded p-2 mb-2 grid grid-cols-6 gap-2 items-end">
                        <div>
                            <LemonLabel>From</LemonLabel>
                            <LemonSelect
                                value={edge.source}
                                options={nodeOptions}
                                onChange={(value) => setConfig(updateEdge(config, edgeIndex, { source: value }))}
                            />
                        </div>
                        <div>
                            <LemonLabel>To</LemonLabel>
                            <LemonSelect
                                value={edge.target}
                                options={nodeOptions}
                                onChange={(value) => setConfig(updateEdge(config, edgeIndex, { target: value }))}
                            />
                        </div>
                        <div>
                            <LemonLabel>Throughput metric</LemonLabel>
                            <LemonInput
                                value={edge.metric_name}
                                onChange={(value) => setConfig(updateEdge(config, edgeIndex, { metric_name: value }))}
                            />
                        </div>
                        <div>
                            <LemonLabel>Aggregation</LemonLabel>
                            <LemonSelect
                                value={edge.aggregation ?? 'sum'}
                                options={AGGREGATION_OPTIONS}
                                onChange={(value) => setConfig(updateEdge(config, edgeIndex, { aggregation: value }))}
                            />
                        </div>
                        <div>
                            <LemonLabel>Baseline</LemonLabel>
                            <LemonInput
                                value={edge.baseline_offset ?? '-7d'}
                                onChange={(value) =>
                                    setConfig(updateEdge(config, edgeIndex, { baseline_offset: value }))
                                }
                            />
                        </div>
                        <LemonButton
                            size="small"
                            status="danger"
                            icon={<IconTrash />}
                            onClick={() => setConfig(removeEdge(config, edgeIndex))}
                        >
                            Remove
                        </LemonButton>
                    </div>
                ))}
            </div>

            <div>
                <div className="flex items-center justify-between mb-2">
                    <h3 className="mb-0">Variables</h3>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={() =>
                            setConfig({ ...config, variables: [...(config.variables ?? []), emptyVariable()] })
                        }
                        data-attr="pipeline-editor-add-variable"
                    >
                        Add variable
                    </LemonButton>
                </div>
                {(config.variables ?? []).map((variable, variableIndex) => (
                    <div key={variableIndex} className="border rounded p-2 mb-2 grid grid-cols-5 gap-2 items-end">
                        <div>
                            <LemonLabel>Key</LemonLabel>
                            <LemonInput
                                value={variable.key}
                                onChange={(value) => setConfig(updateVariable(config, variableIndex, { key: value }))}
                            />
                        </div>
                        <div>
                            <LemonLabel>Label</LemonLabel>
                            <LemonInput
                                value={variable.label}
                                onChange={(value) => setConfig(updateVariable(config, variableIndex, { label: value }))}
                            />
                        </div>
                        <div>
                            <LemonLabel>Filters on label</LemonLabel>
                            <LemonInput
                                value={variable.filter_key}
                                placeholder="e.g. k8s.cluster.name"
                                onChange={(value) =>
                                    setConfig(updateVariable(config, variableIndex, { filter_key: value }))
                                }
                            />
                        </div>
                        <div>
                            <LemonLabel>Options (comma-separated)</LemonLabel>
                            <LemonInput
                                value={(variable.options ?? []).join(',')}
                                onChange={(value) =>
                                    setConfig(
                                        updateVariable(config, variableIndex, {
                                            options: value ? value.split(',').map((option) => option.trim()) : [],
                                        })
                                    )
                                }
                            />
                        </div>
                        <LemonButton
                            size="small"
                            status="danger"
                            icon={<IconTrash />}
                            onClick={() => setConfig(removeVariable(config, variableIndex))}
                        >
                            Remove
                        </LemonButton>
                    </div>
                ))}
            </div>
        </div>
    )
}
