import { type ExperimentExposureQueryResponse, NodeKind } from '~/queries/schema/schema-general'

import {
    type HealthCheckRule,
    type HealthCheckValues,
    type HealthReading,
    healthCheckReadings,
    healthCheckShowsDecidingValue,
    healthExposureSplit,
    healthRuleReadings,
} from './healthCheckValues'

const SRM_RULE: HealthCheckRule = {
    value: 'p_value',
    threshold: 0.001,
    warns: 'below',
    test: 'chi_squared',
    minimum: { value: 'compared_count', threshold: 100 },
}

const MULTIPLE_RULE: HealthCheckRule = {
    value: 'multiple_variant_percentage',
    threshold: 5,
    warns: 'above',
    test: null,
    minimum: { value: 'multiple_variant_count', threshold: 5 },
}

const exposures = (
    totalExposures: Record<string, number>,
    expected?: Record<string, number>
): ExperimentExposureQueryResponse => ({
    kind: NodeKind.ExperimentExposureQuery,
    timeseries: [],
    total_exposures: totalExposures,
    date_range: { date_from: '2026-10-19T00:00:00Z' },
    sample_ratio_mismatch: expected ? { expected, p_value: 0.71 } : undefined,
})

describe('healthCheckValues', () => {
    it.each<{ name: string; values: HealthCheckValues; expected: HealthReading[] }>([
        {
            name: 'the sample ratio check leaves its p-value to the rule',
            values: { p_value: 0.71, compared_count: 9199, multiple_variant_count: 403 },
            expected: [
                { label: 'Users compared', text: '9,199' },
                { label: 'In more than one variant', text: '403' },
            ],
        },
        {
            name: 'the share in more than one variant goes with its count',
            values: {
                exposed_count: 9602,
                multiple_variant_count: 403,
                multiple_variant_percentage: 4.197,
                multiple_variant_handling: 'exclude',
            },
            expected: [
                { label: 'Exposed users', text: '9,602' },
                { label: 'In more than one variant', text: '403 · 4.2%' },
                { label: 'Multiple variant handling', text: 'Exclude from analysis' },
            ],
        },
        {
            name: "the new users in variants the flag doesn't serve go with their share",
            values: { unserved_exposed_count: 2960, unserved_exposed_percentage: 100 },
            expected: [{ label: "New users in variants the flag doesn't serve", text: '2,960 · 100%' }],
        },
        {
            name: 'a metric count reads as n of m',
            values: { metric_count: 3, completed_metric_count: 2, failed_metric_count: 1, calculated_at: null },
            expected: [
                { label: 'Metrics calculated', text: '2 of 3' },
                { label: 'Metrics whose calculation failed', text: '1' },
            ],
        },
        {
            name: 'a deleted flag reads as deleted, whatever else it serves',
            values: { flag_active: true, flag_deleted: true, flag_rolled_out: true, shipped_variant: 'test' },
            expected: [{ label: 'Feature flag', text: 'Deleted' }],
        },
        {
            name: 'a shipped variant names the variant',
            values: { flag_active: true, flag_deleted: false, flag_rolled_out: true, shipped_variant: 'test' },
            expected: [{ label: 'Feature flag', text: 'On, serves only "test"' }],
        },
        {
            name: 'a setting that is off still shows',
            values: { only_count_matured_users: false },
            expected: [{ label: 'Require completed conversion or retention window', text: 'Off' }],
        },
    ])('healthCheckReadings: $name', ({ values, expected }) => {
        expect(healthCheckReadings(values, 'users')).toEqual(expected)
    })

    it.each([
        {
            name: 'a passed test shows its result',
            status: 'passed' as const,
            expected: [
                { label: 'Test', text: 'Chi-squared, exposed users against the planned split' },
                { label: 'Result', text: 'p = 0.71' },
                { label: 'Warns when', text: 'p is below 0.001' },
                { label: 'Warns from', text: '100 users compared' },
            ],
        },
        {
            name: "a test that doesn't apply decided nothing, so it shows no result",
            status: 'not_applicable' as const,
            expected: [
                { label: 'Test', text: 'Chi-squared, exposed users against the planned split' },
                { label: 'Warns when', text: 'p is below 0.001' },
                { label: 'Warns from', text: '100 users compared' },
            ],
        },
    ])('healthRuleReadings: $name', ({ status, expected }) => {
        expect(healthRuleReadings({ status, values: { p_value: 0.71 } }, SRM_RULE, 'users')).toEqual(expected)
    })

    it('healthRuleReadings: no exposure at all reads as none', () => {
        const rule: HealthCheckRule = {
            value: 'exposed_count',
            threshold: 1,
            warns: 'below',
            test: null,
            minimum: { value: 'since_launch_hours', threshold: 24 },
        }

        expect(healthRuleReadings({ status: 'passed', values: {} }, rule, 'groups')).toEqual([
            { label: 'Warns when', text: 'No groups are exposed' },
            { label: 'Warns from', text: '24 hours after launch' },
        ])
    })

    it('healthRuleReadings: the unserved check names the users it counts', () => {
        const rule: HealthCheckRule = {
            value: 'unserved_exposed_percentage',
            threshold: 1,
            warns: 'above',
            test: null,
            minimum: { value: 'unserved_exposed_count', threshold: 5 },
        }

        expect(healthRuleReadings({ status: 'passed', values: {} }, rule, 'users')).toEqual([
            {
                label: 'Warns when',
                text: "More than 1% of the users first exposed after the flag's last save are in variants that it doesn't serve",
            },
            { label: 'Warns from', text: "5 users in variants that the flag doesn't serve" },
        ])
    })

    it.each<{ name: string; values: HealthCheckValues; expected: boolean }>([
        {
            name: 'a share from enough users',
            values: { multiple_variant_percentage: 60, multiple_variant_count: 30 },
            expected: true,
        },
        {
            name: 'a share from too few users',
            values: { multiple_variant_percentage: 60, multiple_variant_count: 3 },
            expected: false,
        },
        { name: 'no share', values: { multiple_variant_count: 30 }, expected: false },
    ])('healthCheckShowsDecidingValue: $name', ({ values, expected }) => {
        expect(healthCheckShowsDecidingValue({ values, rule: MULTIPLE_RULE })).toBe(expected)
    })

    it.each([
        {
            name: 'shares of the compared variants against the planned split',
            answer: exposures({ control: 600, test: 400, $multiple: 50 }, { control: 500, test: 500 }),
            expected: [
                { variant: 'control', exposedCount: 600, exposedPercentage: 60, plannedPercentage: 50 },
                { variant: 'test', exposedCount: 400, exposedPercentage: 40, plannedPercentage: 50 },
            ],
        },
        {
            name: 'no plan before the sample ratio test runs',
            answer: exposures({ control: 30, test: 10, $multiple: 2 }),
            expected: [
                { variant: 'control', exposedCount: 30, exposedPercentage: 75, plannedPercentage: null },
                { variant: 'test', exposedCount: 10, exposedPercentage: 25, plannedPercentage: null },
            ],
        },
        {
            name: 'the variants in the order of the experiment',
            answer: {
                ...exposures({ test: 10, control: 30 }),
                timeseries: [
                    { variant: 'control', days: [], exposure_counts: [] },
                    { variant: 'test', days: [], exposure_counts: [] },
                ],
            },
            expected: [
                { variant: 'control', exposedCount: 30, exposedPercentage: 75, plannedPercentage: null },
                { variant: 'test', exposedCount: 10, exposedPercentage: 25, plannedPercentage: null },
            ],
        },
        { name: 'nothing without exposures', answer: exposures({ control: 0, test: 0 }), expected: null },
    ])('healthExposureSplit: $name', ({ answer, expected }) => {
        expect(healthExposureSplit(answer)).toEqual(expected)
    })
})
