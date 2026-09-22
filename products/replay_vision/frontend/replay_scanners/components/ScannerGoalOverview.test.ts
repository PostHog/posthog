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
                        {
                            type: PropertyFilterType.Session,
                            key: '$entry_current_url',
                            value: ['/pricing'],
                            operator: PropertyOperator.Exact,
                        },
                    ],
                    events: [{ id: 'billing_limit_set', name: 'billing_limit_set', type: 'events', order: 0 }],
                    actions: [{ id: 42, name: 'Completed checkout', type: 'actions', order: 0 }],
                },
            }),
            { experimentName: 'Checkout CTA copy', cohortNames: { 7: 'Power users' } }
        )

        // The session property gets its own row and is not double-counted as a page or cohort, which
        // are pulled from the same top-level properties list but keep their dedicated rows.
        expect(groups).toEqual([
            { label: 'Experiment', values: ['Checkout CTA copy (test variant)'] },
            { label: 'Pages', values: ['/billing', '/checkout'] },
            { label: 'Event', values: ['billing_limit_set'] },
            { label: 'Action', values: ['Completed checkout'] },
            { label: 'Cohort', values: ['Power users'] },
            { label: 'Session', values: ['Entry URL = /pricing'] },
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

    it("appends an event's property conditions so a scoped event doesn't read as every occurrence", () => {
        // A bare "checkout_clicked" chip reads as every click; the country filter has to show or the
        // preview overstates the match.
        const groups = eligibleFilterGroups(
            scanner({
                query: {
                    kind: NodeKind.RecordingsQuery,
                    events: [
                        {
                            id: 'checkout_clicked',
                            name: 'checkout_clicked',
                            type: 'events',
                            order: 0,
                            properties: [
                                {
                                    type: PropertyFilterType.Event,
                                    key: '$geoip_country_code',
                                    value: ['US'],
                                    operator: PropertyOperator.Exact,
                                },
                            ],
                        },
                    ],
                },
            })
        )

        expect(groups).toEqual([{ label: 'Event', values: ['checkout_clicked where Country code = US'] }])
    })

    it('renders a HogQL condition by its comment, so a scoped $exception reads as the error', () => {
        // Error tracking pins $exception to one issue with `issue_id = '...' -- <error>`; the comment
        // is what makes the condition legible instead of an opaque id.
        const groups = eligibleFilterGroups(
            scanner({
                query: {
                    kind: NodeKind.RecordingsQuery,
                    events: [
                        {
                            id: '$exception',
                            name: '$exception',
                            type: 'events',
                            order: 0,
                            properties: [
                                {
                                    type: PropertyFilterType.HogQL,
                                    key: "issue_id = 'abc' -- TypeError: x is not a function",
                                },
                            ],
                        },
                    ],
                },
            })
        )

        expect(groups).toEqual([{ label: 'Event', values: ['$exception where TypeError: x is not a function'] }])
    })

    it('merges top-level person filters into one row, humanizing known keys and keeping custom ones', () => {
        // A recording-level person filter would otherwise be invisible, making the scan look like it
        // watches everyone. A known key humanizes; a custom key with no taxonomy entry keeps its name.
        const groups = eligibleFilterGroups(
            scanner({
                query: {
                    kind: NodeKind.RecordingsQuery,
                    properties: [
                        {
                            type: PropertyFilterType.Person,
                            key: '$browser',
                            value: ['Chrome'],
                            operator: PropertyOperator.Exact,
                        },
                        {
                            type: PropertyFilterType.Person,
                            key: 'plan',
                            value: ['enterprise'],
                            operator: PropertyOperator.Exact,
                        },
                    ],
                },
            })
        )

        expect(groups).toEqual([{ label: 'Person', values: ['Latest browser = Chrome', 'plan = enterprise'] }])
    })

    it('has no groups when the draft watches every recording', () => {
        expect(eligibleFilterGroups(scanner({ query: { kind: NodeKind.RecordingsQuery } }))).toEqual([])
    })
})
