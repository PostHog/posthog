// Pure, immutable update helpers for the pipeline editor's draft config.
// The component computes the next draft with these and dispatches one
// setDraft action, so every edit stays a plain reducer update.

import {
    PipelineConfigApi,
    PipelineEdgeApi,
    PipelineNodeApi,
    PipelineStatApi,
    PipelineThresholdsApi,
    PipelineVariableApi,
} from './types'

let nextSuffix = 1

function uniqueId(prefix: string, taken: string[]): string {
    let candidate = prefix
    while (taken.includes(candidate)) {
        candidate = `${prefix}_${nextSuffix++}`
    }
    return candidate
}

export function emptyStat(node: PipelineNodeApi): PipelineStatApi {
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

export function emptyNode(config: PipelineConfigApi): PipelineNodeApi {
    const id = uniqueId(
        'new_node',
        config.nodes.map((n) => n.id)
    )
    return { id, name: 'New node', kind: '', stats: [], headline_stat_ids: [], links: [], note: '' }
}

export function emptyEdge(config: PipelineConfigApi): PipelineEdgeApi | null {
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

export function emptyVariable(): PipelineVariableApi {
    return { key: 'environment', label: 'Environment', filter_key: '', options: [] }
}

export function updateNode(
    config: PipelineConfigApi,
    index: number,
    patch: Partial<PipelineNodeApi>
): PipelineConfigApi {
    const previousId = config.nodes[index].id
    const nodes = config.nodes.map((node, i) => (i === index ? { ...node, ...patch } : node))
    // Renaming a node id keeps its edges attached.
    const newId = patch.id
    const edges =
        newId && newId !== previousId
            ? (config.edges ?? []).map((edge) => ({
                  ...edge,
                  source: edge.source === previousId ? newId : edge.source,
                  target: edge.target === previousId ? newId : edge.target,
              }))
            : config.edges
    return { ...config, nodes, edges }
}

export function removeNode(config: PipelineConfigApi, index: number): PipelineConfigApi {
    const removedId = config.nodes[index].id
    return {
        ...config,
        nodes: config.nodes.filter((_, i) => i !== index),
        edges: (config.edges ?? []).filter((edge) => edge.source !== removedId && edge.target !== removedId),
    }
}

/** Set one severity's upper bound, keeping any lower bound already configured.
 * The editor only exposes the upper bound, so replacing the whole severity
 * object would silently drop a lower bound set through the API. Clearing the
 * input drops the severity only when there is no lower bound left to keep. */
export function withUpperBound(
    thresholds: PipelineThresholdsApi | null | undefined,
    severity: 'warn' | 'crit',
    upper: number | undefined
): PipelineThresholdsApi {
    const existing = thresholds?.[severity]
    const lower = existing?.lower ?? null
    if (upper === undefined) {
        return { ...thresholds, [severity]: lower === null ? null : { lower } }
    }
    return { ...thresholds, [severity]: lower === null ? { upper } : { lower, upper } }
}

export function updateStat(
    config: PipelineConfigApi,
    nodeIndex: number,
    statIndex: number,
    patch: Partial<PipelineStatApi>
): PipelineConfigApi {
    return {
        ...config,
        nodes: config.nodes.map((node, i) =>
            i === nodeIndex
                ? { ...node, stats: node.stats.map((stat, j) => (j === statIndex ? { ...stat, ...patch } : stat)) }
                : node
        ),
    }
}

export function removeStat(config: PipelineConfigApi, nodeIndex: number, statIndex: number): PipelineConfigApi {
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
    config: PipelineConfigApi,
    index: number,
    patch: Partial<PipelineEdgeApi>
): PipelineConfigApi {
    return { ...config, edges: (config.edges ?? []).map((edge, i) => (i === index ? { ...edge, ...patch } : edge)) }
}

export function removeEdge(config: PipelineConfigApi, index: number): PipelineConfigApi {
    return { ...config, edges: (config.edges ?? []).filter((_, i) => i !== index) }
}

export function updateVariable(
    config: PipelineConfigApi,
    index: number,
    patch: Partial<PipelineVariableApi>
): PipelineConfigApi {
    return {
        ...config,
        variables: (config.variables ?? []).map((variable, i) => (i === index ? { ...variable, ...patch } : variable)),
    }
}

export function removeVariable(config: PipelineConfigApi, index: number): PipelineConfigApi {
    return { ...config, variables: (config.variables ?? []).filter((_, i) => i !== index) }
}
