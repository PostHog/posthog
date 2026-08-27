// Pure, immutable update helpers for the pipeline editor's draft config.
// The component computes the next draft with these and dispatches one
// setDraft action, so every edit stays a plain reducer update.

import {
    PipelineConfigType,
    PipelineEdgeType,
    PipelineNodeType,
    PipelineStatType,
    PipelineThresholdsType,
    PipelineVariableType,
} from './types'

let nextSuffix = 1

function uniqueId(prefix: string, taken: string[]): string {
    let candidate = prefix
    while (taken.includes(candidate)) {
        candidate = `${prefix}_${nextSuffix++}`
    }
    return candidate
}

export function emptyStat(node: PipelineNodeType): PipelineStatType {
    return {
        id: uniqueId(
            'new_stat',
            node.stats.map((s) => s.id)
        ),
        label: 'New stat',
        format: 'count',
        metric_name: '',
        aggregation: 'sum',
        filters: [],
    }
}

export function emptyNode(config: PipelineConfigType): PipelineNodeType {
    const id = uniqueId(
        'new_node',
        config.nodes.map((n) => n.id)
    )
    return { id, name: 'New node', kind: '', stats: [], headline_stat_ids: [], links: [], note: '' }
}

export function emptyEdge(config: PipelineConfigType): PipelineEdgeType | null {
    if (config.nodes.length < 2) {
        return null
    }
    return {
        source: config.nodes[0].id,
        target: config.nodes[1].id,
        metric_name: '',
        aggregation: 'sum',
        baseline_offset: '-7d',
        hot_multiplier: 2.0,
    }
}

export function emptyVariable(): PipelineVariableType {
    return { key: 'environment', label: 'Environment', filter_key: '', options: [] }
}

export function updateNode(
    config: PipelineConfigType,
    index: number,
    patch: Partial<PipelineNodeType>
): PipelineConfigType {
    const previousId = config.nodes[index].id
    const nodes = config.nodes.map((node, i) => (i === index ? { ...node, ...patch } : node))
    // Renaming a node id keeps its edges attached.
    const newId = patch.id
    const edges =
        newId && newId !== previousId
            ? config.edges.map((edge) => ({
                  ...edge,
                  source: edge.source === previousId ? newId : edge.source,
                  target: edge.target === previousId ? newId : edge.target,
              }))
            : config.edges
    return { ...config, nodes, edges }
}

export function removeNode(config: PipelineConfigType, index: number): PipelineConfigType {
    const removedId = config.nodes[index].id
    return {
        ...config,
        nodes: config.nodes.filter((_, i) => i !== index),
        edges: config.edges.filter((edge) => edge.source !== removedId && edge.target !== removedId),
    }
}

/** Set one severity's upper bound, keeping any lower bound already configured.
 * The editor only exposes the upper bound, so replacing the whole severity
 * object would silently drop a lower bound set through the API. Clearing the
 * input drops the severity only when there is no lower bound left to keep. */
export function withUpperBound(
    thresholds: PipelineThresholdsType | null | undefined,
    severity: 'warn' | 'crit',
    upper: number | undefined
): PipelineThresholdsType {
    const existing = thresholds?.[severity]
    const lower = existing?.lower ?? null
    if (upper === undefined) {
        return { ...thresholds, [severity]: lower === null ? null : { lower } }
    }
    return { ...thresholds, [severity]: lower === null ? { upper } : { lower, upper } }
}

export function updateStat(
    config: PipelineConfigType,
    nodeIndex: number,
    statIndex: number,
    patch: Partial<PipelineStatType>
): PipelineConfigType {
    return {
        ...config,
        nodes: config.nodes.map((node, i) =>
            i === nodeIndex
                ? { ...node, stats: node.stats.map((stat, j) => (j === statIndex ? { ...stat, ...patch } : stat)) }
                : node
        ),
    }
}

export function removeStat(config: PipelineConfigType, nodeIndex: number, statIndex: number): PipelineConfigType {
    return {
        ...config,
        nodes: config.nodes.map((node, i) =>
            i === nodeIndex
                ? {
                      ...node,
                      stats: node.stats.filter((_, j) => j !== statIndex),
                      headline_stat_ids: (node.headline_stat_ids ?? []).filter((id) => id !== node.stats[statIndex].id),
                  }
                : node
        ),
    }
}

export function updateEdge(
    config: PipelineConfigType,
    index: number,
    patch: Partial<PipelineEdgeType>
): PipelineConfigType {
    return { ...config, edges: config.edges.map((edge, i) => (i === index ? { ...edge, ...patch } : edge)) }
}

export function removeEdge(config: PipelineConfigType, index: number): PipelineConfigType {
    return { ...config, edges: config.edges.filter((_, i) => i !== index) }
}

export function updateVariable(
    config: PipelineConfigType,
    index: number,
    patch: Partial<PipelineVariableType>
): PipelineConfigType {
    return {
        ...config,
        variables: (config.variables ?? []).map((variable, i) => (i === index ? { ...variable, ...patch } : variable)),
    }
}

export function removeVariable(config: PipelineConfigType, index: number): PipelineConfigType {
    return { ...config, variables: (config.variables ?? []).filter((_, i) => i !== index) }
}
