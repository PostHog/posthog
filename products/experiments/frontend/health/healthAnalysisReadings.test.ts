import type { ExperimentHealthAnalysisSetupApi } from '../generated/api.schemas'
import { healthAnalysisReadings } from './healthAnalysisReadings'

const UNSET_BAYESIAN: ExperimentHealthAnalysisSetupApi = {
    stats_method: 'bayesian',
    confidence_level: 0.95,
    sequential_testing: null,
    sequential_testing_from_project_default: false,
    cuped: false,
    cuped_lookback_days: null,
    cuped_from_project_default: true,
    filters_test_accounts: true,
    test_account_filter_count: 2,
    multiple_variant_handling: 'exclude',
    only_count_matured_users: false,
    baseline_variant: 'control',
    excluded_variants: [],
}

describe('healthAnalysisReadings', () => {
    it.each([
        {
            name: 'tags only the settings that the project default decides',
            analysis: UNSET_BAYESIAN,
            expected: {
                Statistics: 'Bayesian, 95% credible interval',
                CUPED: 'Off (project default)',
                // `pluralize` joins the count and the noun with a non-breaking space.
                'Internal and test users': 'Left out by 2\u00a0filters',
                'Multiple variant handling': 'Exclude from analysis',
                'Require completed conversion or retention window': 'Off',
                'Baseline variant': 'control',
            },
        },
        {
            name: 'reads the frequentist settings that the experiment sets',
            analysis: {
                ...UNSET_BAYESIAN,
                stats_method: 'frequentist',
                confidence_level: 0.9,
                sequential_testing: true,
                sequential_testing_from_project_default: true,
                cuped: true,
                cuped_lookback_days: 14,
                cuped_from_project_default: false,
                filters_test_accounts: false,
                excluded_variants: ['test-2'],
            },
            expected: {
                Statistics: 'Frequentist, 90% confidence',
                'Sequential testing': 'On (project default)',
                CUPED: 'On, 14-day lookback',
                'Internal and test users': 'Counted',
                'Multiple variant handling': 'Exclude from analysis',
                'Require completed conversion or retention window': 'Off',
                'Baseline variant': 'control',
                'Variants left out of the results': 'test-2',
            },
        },
    ] as { name: string; analysis: ExperimentHealthAnalysisSetupApi; expected: Record<string, string> }[])(
        '$name',
        ({ analysis, expected }) => {
            const readings = healthAnalysisReadings(analysis)
            expect(
                Object.fromEntries(readings.map((line) => [line.label, 'text' in line ? line.text : line.time]))
            ).toEqual(expected)
        }
    )
})
