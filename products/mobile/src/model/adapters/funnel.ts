import { asRecord, isRecord } from '@/lib/records'

import type { FunnelStepView, FunnelView } from '../views'
import { hasBreakdown } from './metric'

type JsonRecord = Record<string, unknown>

function finite(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function percent(part: number, whole: number): number | null {
    return whole > 0 ? (part / whole) * 100 : null
}

function stepName(step: JsonRecord | undefined, index: number): string {
    const custom = step?.custom_name
    if (typeof custom === 'string' && custom !== '') {
        return custom
    }
    return typeof step?.name === 'string' && step.name !== '' ? step.name : `Step ${index + 1}`
}

/**
 * True for a funnel the phone draws: the steps layout, without a cohort breakdown. A cohort breakdown can count a
 * person in several cohorts, so the sum of its values is wrong and the funnel opens on the web, like the trends and
 * time-to-convert layouts.
 */
export function isDrawableFunnel(query: unknown): boolean {
    const source = asRecord(asRecord(query)?.source) ?? asRecord(query)
    if (source?.kind !== 'FunnelsQuery') {
        return false
    }
    const layout = asRecord(source.funnelsFilter)?.funnelVizType
    if (layout !== undefined && layout !== null && layout !== 'steps') {
        return false
    }
    return !(hasBreakdown(source) && asRecord(source.breakdownFilter)?.breakdown_type === 'cohort')
}

/**
 * The steps of a drawable funnel. A breakdown answers one list of steps per value; their counts add up to the whole
 * funnel because each person falls under one value.
 */
export function funnelView(query: unknown, result: unknown): FunnelView | null {
    if (!isDrawableFunnel(query) || !Array.isArray(result)) {
        return null
    }
    const byBreakdown = result.length > 0 && result.every(Array.isArray)
    const groups: JsonRecord[][] = byBreakdown
        ? result.map((group: unknown[]) => group.filter(isRecord))
        : [result.filter(isRecord)]
    const first = groups[0] ?? []
    const counts = first.map((_, index) =>
        groups.reduce((total, group) => total + (finite(group[index]?.count) ?? 0), 0)
    )
    const entered = counts[0] ?? 0
    const steps = first.map((step, index): FunnelStepView => {
        const count = counts[index] ?? 0
        const before = index > 0 ? (counts[index - 1] ?? 0) : null
        return {
            key: `${index}:${stepName(step, index)}`,
            name: stepName(step, index),
            count,
            percentOfFirst: percent(count, entered),
            percentOfPrevious: before === null ? null : percent(count, before),
            droppedOff: before === null ? null : Math.max(0, before - count),
            // Medians of the breakdown values do not combine into the median of the whole funnel.
            medianSeconds: byBreakdown || index === 0 ? null : (finite(step.median_conversion_time) ?? null),
        }
    })
    const last = counts[counts.length - 1]
    return {
        steps,
        conversion: steps.length > 1 && last !== undefined ? percent(last, entered) : null,
        breakdownValues: byBreakdown ? groups.length : 0,
    }
}
