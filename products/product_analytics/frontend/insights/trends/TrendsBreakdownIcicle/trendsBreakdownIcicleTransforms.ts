import type { FlameNode } from '@posthog/quill-charts'

import { CompareLabelType, type TrendResult } from '~/types'

export type BreakdownIcicleValue = string | number

export interface BreakdownIcicleMeta {
    /** The raw breakdown values from the root down to this node, one per breakdown level. */
    breakdownValues: BreakdownIcicleValue[]
}

export type BreakdownIcicleResult = Pick<
    TrendResult,
    'aggregated_value' | 'breakdown_value' | 'compare_label' | 'order' | 'action' | 'label'
>

export interface BuildBreakdownIcicleOptions<R extends BreakdownIcicleResult> {
    /** Name of the top row. */
    rootLabel: string
    /** Display name of a result's series, used as the first level when there are several series. */
    seriesLabel: (result: R) => string
    /** Display text for one breakdown value at a breakdown level (0 for the first breakdown). */
    formatValue: (value: BreakdownIcicleValue, level: number) => string
}

interface TrieNode {
    name: string
    value: number
    breakdownValues: BreakdownIcicleValue[]
    children: Map<string, TrieNode>
}

const seriesKeyOf = (result: BreakdownIcicleResult): string =>
    String(result.order ?? result.action?.order ?? result.label)

function breakdownPath(result: BreakdownIcicleResult): BreakdownIcicleValue[] {
    const value = result.breakdown_value
    if (value === undefined || value === null || value === '') {
        return []
    }
    return Array.isArray(value) ? value : [value]
}

function toFlameNode(node: TrieNode, group: string | undefined): FlameNode<BreakdownIcicleMeta> {
    return {
        name: node.name,
        value: node.value,
        group,
        meta: { breakdownValues: node.breakdownValues },
        children: Array.from(node.children.values(), (child) => toFlameNode(child, group ?? child.name)),
    }
}

/**
 * Nests total-value trend results into an icicle tree: the overall total on top, then one level per
 * breakdown (and a series level first when the insight has several series). A parent's value is the
 * sum of its children's, so a person counted under two breakdown values counts twice, as in a pie.
 * Rows of a previous period are skipped, because the tree shows one period.
 */
export function buildBreakdownIcicle<R extends BreakdownIcicleResult>(
    results: R[],
    { rootLabel, seriesLabel, formatValue }: BuildBreakdownIcicleOptions<R>
): FlameNode<BreakdownIcicleMeta> {
    const current = results.filter((result) => result.compare_label !== CompareLabelType.Previous)
    const seriesLevel = new Set(current.map(seriesKeyOf)).size > 1
    const root: TrieNode = { name: rootLabel, value: 0, breakdownValues: [], children: new Map() }

    for (const result of current) {
        const value = result.aggregated_value
        if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
            continue
        }
        root.value += value
        let node = root
        if (seriesLevel) {
            const key = `series:${seriesKeyOf(result)}`
            let child = node.children.get(key)
            if (!child) {
                child = { name: seriesLabel(result), value: 0, breakdownValues: [], children: new Map() }
                node.children.set(key, child)
            }
            child.value += value
            node = child
        }
        breakdownPath(result).forEach((breakdownValue, level) => {
            const key = String(breakdownValue)
            let child = node.children.get(key)
            if (!child) {
                child = {
                    name: formatValue(breakdownValue, level),
                    value: 0,
                    breakdownValues: [...node.breakdownValues, breakdownValue],
                    children: new Map(),
                }
                node.children.set(key, child)
            }
            child.value += value
            node = child
        })
    }

    // The first level below the total picks the color, and everything under it keeps that color.
    return toFlameNode(root, undefined)
}
