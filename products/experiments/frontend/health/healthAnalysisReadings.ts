import { pluralize } from 'lib/utils/strings'

import type { ExperimentHealthAnalysisSetupApi } from '../generated/api.schemas'
import { HANDLING_LABELS, type HealthReading } from './healthCheckValues'

function percentage(fraction: number): string {
    return `${Math.round(fraction * 1000) / 10}%`
}

function onOff(value: boolean): string {
    return value ? 'On' : 'Off'
}

function withProjectDefault(text: string, fromProjectDefault: boolean): string {
    return fromProjectDefault ? `${text} (project default)` : text
}

function statisticsText({ stats_method, confidence_level }: ExperimentHealthAnalysisSetupApi): string {
    return stats_method === 'frequentist'
        ? `Frequentist, ${percentage(confidence_level)} confidence`
        : `Bayesian, ${percentage(confidence_level)} credible interval`
}

function sequentialReading(analysis: ExperimentHealthAnalysisSetupApi): HealthReading | null {
    if (analysis.sequential_testing === null) {
        return null
    }
    return {
        label: 'Sequential testing',
        text: withProjectDefault(onOff(analysis.sequential_testing), analysis.sequential_testing_from_project_default),
    }
}

function cupedText({ cuped_lookback_days, cuped_from_project_default }: ExperimentHealthAnalysisSetupApi): string {
    const text = cuped_lookback_days === null ? 'Off' : `On, ${cuped_lookback_days}-day lookback`
    return withProjectDefault(text, cuped_from_project_default)
}

function testUsersReading({
    filters_test_accounts,
    test_account_filter_count,
}: ExperimentHealthAnalysisSetupApi): HealthReading | null {
    if (filters_test_accounts === null) {
        return null
    }
    if (!filters_test_accounts) {
        return { label: 'Internal and test users', text: 'Counted' }
    }
    return {
        label: 'Internal and test users',
        text:
            test_account_filter_count > 0
                ? `Left out by ${pluralize(test_account_filter_count, 'filter')}`
                : 'Counted, because the project has no test account filters',
    }
}

export function healthAnalysisReadings(analysis: ExperimentHealthAnalysisSetupApi): HealthReading[] {
    const handling = analysis.multiple_variant_handling
    return [
        { label: 'Statistics', text: statisticsText(analysis) },
        sequentialReading(analysis),
        { label: 'CUPED', text: cupedText(analysis) },
        testUsersReading(analysis),
        handling === null ? null : { label: 'Multiple variant handling', text: HANDLING_LABELS[handling] ?? handling },
        {
            label: 'Require completed conversion or retention window',
            text: onOff(analysis.only_count_matured_users),
        },
        { label: 'Baseline variant', text: analysis.baseline_variant },
        analysis.excluded_variants.length > 0
            ? { label: 'Variants left out of the results', text: analysis.excluded_variants.join(', ') }
            : null,
    ].filter((line): line is HealthReading => line !== null)
}
