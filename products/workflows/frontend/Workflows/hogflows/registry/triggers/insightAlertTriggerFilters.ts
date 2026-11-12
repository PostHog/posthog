import { PropertyFilterType, PropertyOperator } from '~/types'

import { triggersOnInternalEvent } from './internalEventTriggerConfig'

/** pinned: internal event an insight alert emits each time it notifies */
export const INSIGHT_ALERT_FIRING_EVENT = '$insight_alert_firing'

/** The stored trigger config an insight alert workflow uses. */
export type InternalEventInsightAlertTriggerConfig = {
    type: 'internal-event'
    filters: {
        source: 'internal-events'
        events: { id: string; type: 'events' }[]
        properties?: any[]
    }
}

export function isInsightAlertTriggerConfig(config: unknown): config is InternalEventInsightAlertTriggerConfig {
    return triggersOnInternalEvent(config, INSIGHT_ALERT_FIRING_EVENT)
}

export interface InsightAlertTriggerFilters {
    alertIds: string[]
    /** Filters a person added beside the alert picker, kept as they are. */
    additional: Record<string, any>[]
}

function isAlertIdFilter(property: Record<string, any> | undefined): boolean {
    return property?.key === 'alert_id' && (property.operator ?? PropertyOperator.Exact) === PropertyOperator.Exact
}

export function decodeInsightAlertFilters(properties: Record<string, any>[] | undefined): InsightAlertTriggerFilters {
    const list = Array.isArray(properties) ? properties : []
    const entry = list.find(isAlertIdFilter)
    const value = entry ? (Array.isArray(entry.value) ? entry.value : [entry.value]) : []
    return {
        alertIds: value.filter((item: unknown): item is string => typeof item === 'string' && item !== ''),
        additional: list.filter((property) => !isAlertIdFilter(property)),
    }
}

export function encodeInsightAlertFilters(filters: InsightAlertTriggerFilters): Record<string, any>[] {
    const alertFilter = filters.alertIds.length
        ? [
              {
                  key: 'alert_id',
                  value: filters.alertIds,
                  operator: PropertyOperator.Exact,
                  type: PropertyFilterType.Event,
              },
          ]
        : []
    return [...alertFilter, ...filters.additional]
}
