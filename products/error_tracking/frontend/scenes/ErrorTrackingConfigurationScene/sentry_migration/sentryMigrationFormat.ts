import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { genericOperatorMap } from 'lib/utils/operators'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import type { PropertyGroupFilterValueApi, SentryMigrationRateLimitApi } from '../../../generated/api.schemas'

export interface SuppressionFilterRow {
    property: string
    operator: string
    value: string
}

function formatWindow(minutes: number): string {
    if (minutes % 60 === 0) {
        const hours = minutes / 60
        return hours === 1 ? '1 hour' : `${hours} hours`
    }
    return `${minutes} minutes`
}

export function formatRateLimit(rateLimit: SentryMigrationRateLimitApi): string {
    return `${rateLimit.value.toLocaleString()} exceptions per ${formatWindow(rateLimit.bucket_size_minutes)}`
}

/** One readable row per condition of a flat suppression rule, in the words the rule editor uses. */
export function describeSuppressionFilters(filters: PropertyGroupFilterValueApi): SuppressionFilterRow[] {
    return filters.values.flatMap((condition) => {
        const key = 'key' in condition ? condition.key : undefined
        if (!key || !('operator' in condition)) {
            return []
        }
        const operator = String(condition.operator ?? 'exact')
        const value = 'value' in condition ? condition.value : undefined
        return [
            {
                property: getCoreFilterDefinition(key, TaxonomicFilterGroupType.EventProperties)?.label ?? key,
                // genericOperatorMap labels start with a symbol, such as "∼ matches regex".
                operator: (genericOperatorMap[operator] ?? operator).split(' ').slice(1).join(' ') || operator,
                value: Array.isArray(value) ? value.join(', ') : String(value ?? ''),
            },
        ]
    })
}
