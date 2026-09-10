import { NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import type { ReplayScanner } from '../types'
import { eligibleFilterGroups } from './ScannerGoalOverview'

const scanner = (overrides: Partial<ReplayScanner> = {}): ReplayScanner =>
    ({
        id: 'new',
        name: 'Scanner',
        scanner_type: 'monitor',
        scanner_config: { prompt: 'Did the user struggle?' },
        sampling_rate: 1,
        sampling_mode: 'comprehensive',
        model: 'gemini-3-flash-preview',
        experiment_targeting: null,
        query: null,
        ...overrides,
    }) as ReplayScanner

describe('eligibleFilterGroups', () => {
    it('labels each kind of filter the draft can produce', () => {
        // The values alone don't say what narrows the scan, and an action or a cohort reads as a
        // bare name or an id, so the label is what tells the reader which kind each one is.
        const groups = eligibleFilterGroups(
            scanner({
                experiment_targeting: { experiment_id: 11, variant: 'test' },
                query: {
                    kind: NodeKind.RecordingsQuery,
                    properties: [
                        {
                            type: PropertyFilterType.Recording,
                            key: 'visited_page',
                            value: ['/billing', '/checkout'],
                            operator: PropertyOperator.Regex,
                        },
                        { type: PropertyFilterType.Cohort, key: 'id', value: 7, operator: PropertyOperator.In },
                    ],
                    events: [{ id: 'billing_limit_set', name: 'billing_limit_set', type: 'events', order: 0 }],
                    actions: [{ id: 42, name: 'Completed checkout', type: 'actions', order: 0 }],
                },
            }),
            { experimentName: 'Checkout CTA copy', cohortNames: { 7: 'Power users' } }
        )

        expect(groups).toEqual([
            { label: 'Experiment', values: ['Checkout CTA copy (test variant)'] },
            { label: 'Pages', values: ['/billing', '/checkout'] },
            { label: 'Event', values: ['billing_limit_set'] },
            { label: 'Action', values: ['Completed checkout'] },
            { label: 'Cohort', values: ['Power users'] },
        ])
    })

    it('names an experiment and a cohort it cannot resolve yet', () => {
        // Both load separately from the form, so the row has to stand on its own until they arrive.
        const groups = eligibleFilterGroups(
            scanner({
                experiment_targeting: { experiment_id: 11, variant: null },
                query: {
                    kind: NodeKind.RecordingsQuery,
                    properties: [
                        { type: PropertyFilterType.Cohort, key: 'id', value: 7, operator: PropertyOperator.In },
                    ],
                },
            })
        )

        expect(groups).toEqual([
            { label: 'Experiment', values: ['Experiment 11 (all variants)'] },
            { label: 'Cohort', values: ['Cohort 7'] },
        ])
    })

    it('has no groups when the draft watches every recording', () => {
        expect(eligibleFilterGroups(scanner({ query: { kind: NodeKind.RecordingsQuery } }))).toEqual([])
    })
})
