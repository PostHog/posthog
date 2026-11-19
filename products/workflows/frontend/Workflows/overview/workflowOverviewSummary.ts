import { humanFriendlyDuration } from 'lib/utils/durations'

import { PERSON_FREQUENCY_OPTIONS, getRegisteredTriggerTypes } from '../hogflows/registry/triggers/triggerTypeRegistry'
import { TTL_OPTIONS } from '../hogflows/steps/StepTrigger'
import type { HogFlow } from '../hogflows/types'

export const EXIT_CONDITION_LABELS: Record<HogFlow['exit_condition'], string> = {
    exit_only_at_end: 'People leave the workflow when they reach the end.',
    exit_on_trigger_not_matched: 'People leave the workflow when they no longer match the trigger filters.',
    exit_on_conversion: 'People leave the workflow when they meet the conversion goal.',
    exit_on_trigger_not_matched_or_conversion:
        'People leave the workflow when they no longer match the trigger filters, or when they meet the conversion goal.',
}

type TriggerType = NonNullable<HogFlow['trigger']>['type']
// These triggers always match a registered trigger type, which supplies their label.
type BuiltInTriggerType = Exclude<TriggerType, 'cohort' | 'data-warehouse-table' | 'data-warehouse-view'>

const BUILT_IN_TRIGGER_LABELS: Record<BuiltInTriggerType, string> = {
    event: 'when they perform',
    webhook: 'when a webhook is received',
    manual: 'when someone runs it manually',
    schedule: 'on a schedule',
    tracking_pixel: 'when a tracking pixel loads',
    batch: 'when a batch run starts',
    'internal-event': 'when PostHog records',
    api: 'when your code sends it through the API',
}

export function triggerLeadIn(trigger: HogFlow['trigger']): string {
    if (!trigger) {
        return 'No trigger is set up yet.'
    }
    const registered = getRegisteredTriggerTypes().find((t) => t.matchConfig?.(trigger))
    if (registered) {
        return `People enter this workflow on ${registered.label.toLowerCase()}`
    }
    return `People enter this workflow ${BUILT_IN_TRIGGER_LABELS[trigger.type as BuiltInTriggerType] ?? 'when the trigger fires'}`
}

export function triggerEventNames(trigger: HogFlow['trigger']): string[] {
    if (!trigger || !('filters' in trigger) || !trigger.filters) {
        return []
    }
    const filters = trigger.filters as { events?: { name?: string; id?: string }[]; actions?: { name?: string }[] }
    return [...(filters.events ?? []), ...(filters.actions ?? [])]
        .map((entry) => entry.name || ('id' in entry ? String(entry.id ?? '') : ''))
        .filter(Boolean)
}

export function triggerPropertyFilters(trigger: HogFlow['trigger']): any[] {
    if (!trigger || !('filters' in trigger) || !trigger.filters) {
        return []
    }
    return (trigger.filters as { properties?: any[] }).properties ?? []
}

export function frequencySummary(workflow: Pick<HogFlow, 'trigger' | 'trigger_masking'>): string {
    const hash = workflow.trigger_masking?.hash ?? null
    const registered = workflow.trigger
        ? getRegisteredTriggerTypes().find((t) => t.matchConfig?.(workflow.trigger))
        : undefined
    const option = (registered?.frequencyOptions ?? PERSON_FREQUENCY_OPTIONS).find((o) => o.value === hash)
    if (!hash) {
        return 'Every time the trigger fires'
    }
    const label = option?.label ?? 'Limited by a custom rule'
    const ttlSeconds = workflow.trigger_masking?.ttl ?? null
    const ttlLabel =
        ttlSeconds === null
            ? null
            : (TTL_OPTIONS.find((o) => o.value === ttlSeconds)?.label ?? humanFriendlyDuration(ttlSeconds))
    const base = option?.fixedTtl || !ttlLabel ? label : `${label} per ${ttlLabel}`
    // With a threshold of N, the 1st, (N + 1)th, (2N + 1)th... matching events start a run.
    const threshold = workflow.trigger_masking?.threshold ?? null
    return threshold && threshold > 1 ? `${base}, then again every ${threshold} matching events` : base
}

type GoalEntity = { name?: string | null; id?: string | number | null }

export function conversionGoalEvents(conversion: HogFlow['conversion']): string[] {
    return (conversion?.events ?? [])
        .flatMap((goal) => [
            ...((goal.filters?.events ?? []) as GoalEntity[]).map((event) => event.name || String(event.id ?? '')),
            ...((goal.filters?.actions ?? []) as GoalEntity[]).map(
                (action) => action.name || (action.id != null ? `Action ${action.id}` : '')
            ),
        ])
        .filter(Boolean)
}
