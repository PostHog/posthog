import { FilterLogicalOperator, PropertyOperator, UniversalFiltersGroup } from '~/types'

import {
    SERVICE_NAME_FILTER,
    SEVERITY_LEVEL_FILTER,
} from 'products/logs/frontend/components/LogsViewer/FacetRail/facetFilters'

export interface LogsMetricRuleSeed {
    /** Distinguishes form logic instances, so a new seed always gets fresh form defaults. */
    seedKey: string
    name: string
    metric_name: string
    /** Single-level group, the shape the rule form's filter editor works on. */
    filter_group: UniversalFiltersGroup
}

// Keeps only the characters METRIC_NAME_PATTERN (metric_rules_api.py) accepts; the 'log.'
// prefix below supplies the leading letter the pattern requires.
function sanitizeMetricNamePart(part: string): string {
    return part.toLowerCase().replace(/[^a-z0-9._-]+/g, '_')
}

/**
 * Prefills a metric rule from one log row: filter on the row's service and severity, and derive
 * a name and metric name from them. The filters reuse the facet targets so a seeded rule matches
 * exactly what the viewer's own service/severity chips would.
 */
export function buildMetricRuleSeedFromLog(log: {
    uuid: string
    severity_text: string
    resource_attributes?: Record<string, unknown>
}): LogsMetricRuleSeed {
    const serviceName = String(log.resource_attributes?.['service.name'] ?? '').trim()
    const severity = (log.severity_text ?? '').trim()

    const values: UniversalFiltersGroup['values'] = []
    if (serviceName) {
        values.push({ ...SERVICE_NAME_FILTER, operator: PropertyOperator.Exact, value: [serviceName] } as never)
    }
    if (severity) {
        values.push({ ...SEVERITY_LEVEL_FILTER, operator: PropertyOperator.Exact, value: [severity] } as never)
    }

    const nameParts = [serviceName, severity].filter(Boolean)
    const metricNameParts = nameParts.map(sanitizeMetricNamePart).filter(Boolean)

    return {
        seedKey: log.uuid,
        name: nameParts.length ? `${nameParts.join(' ')} logs` : '',
        metric_name: metricNameParts.length ? `log.${metricNameParts.join('.')}` : '',
        filter_group: { type: FilterLogicalOperator.And, values },
    }
}
