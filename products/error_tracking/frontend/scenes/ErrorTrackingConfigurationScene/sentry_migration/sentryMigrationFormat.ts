import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { genericOperatorMap } from 'lib/utils/operators'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import type {
    PropertyGroupFilterValueApi,
    SentryMigrationFitEnumApi,
    SentryMigrationRateLimitApi,
} from '../../../generated/api.schemas'
import type { SentryImportPlan } from './sentryMigrationSelection'

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

export const FIT_LABELS: Record<SentryMigrationFitEnumApi, string> = {
    good: 'Same behavior',
    partial: 'Close match',
    unsupported: "Can't import",
}

/** One line for each kind of change that an import of the selected settings makes in PostHog. */
export function describeImportPlan(importPlan: SentryImportPlan): string[] {
    const changes: string[] = []
    if (importPlan.rateLimit) {
        changes.push(`Sets the project rate limit to ${formatRateLimit(importPlan.rateLimit)}`)
    }
    if (importPlan.manualRuleCount > 0) {
        changes.push(
            `Creates ${importPlan.manualRuleCount} manual suppression ${importPlan.manualRuleCount === 1 ? 'rule' : 'rules'}`
        )
    }
    if (importPlan.automaticRuleNames.length > 0) {
        changes.push(`Turns on these automatic suppression rules: ${importPlan.automaticRuleNames.join(', ')}`)
    }
    return changes
}

export function importButtonLabel(selectedCount: number): string {
    if (selectedCount === 0) {
        return 'Import'
    }
    return selectedCount === 1 ? 'Import 1 setting' : `Import ${selectedCount} settings`
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
