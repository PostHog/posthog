import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import {
    IssueFilterDraft,
    issueFilterDraftFromStored,
    issueFilterPayloadFromDraft,
    withQuickFilterPick,
} from './errorTrackingIssueFilters'

const PRODUCTION = {
    key: '$environment',
    type: PropertyFilterType.Event,
    operator: PropertyOperator.Exact,
    value: ['production'],
}

function draft(
    values: any[],
    overrides: Partial<IssueFilterDraft> = {},
    type = FilterLogicalOperator.And
): IssueFilterDraft {
    return {
        severity: null,
        assignee: null,
        filterGroup: { type: FilterLogicalOperator.And, values: [{ type, values }] },
        ...overrides,
    }
}

describe('errorTrackingIssueFilters', () => {
    it('round-trips a stored filter through the modal controls', () => {
        const stored = {
            properties: [
                PRODUCTION,
                { key: 'name', type: 'event', operator: 'icontains', value: 'timeout' },
                { key: 'severity', type: 'event', operator: 'exact', value: ['high'] },
                { key: 'assignee', type: 'event', operator: 'exact', value: ['{"type":"user","id":7}'] },
            ],
            bytecode: ['_H', 1],
        }

        const parsed = issueFilterDraftFromStored(stored)

        expect(parsed.severity).toEqual('high')
        expect(parsed.assignee).toEqual({ type: 'user', id: 7 })
        // The issue name shows under "Issues", as the Issues screen labels it.
        expect((parsed.filterGroup.values[0] as UniversalFiltersGroup).values).toEqual([
            PRODUCTION,
            { key: 'name', type: PropertyFilterType.ErrorTrackingIssue, operator: 'icontains', value: 'timeout' },
        ])
        expect(issueFilterPayloadFromDraft(parsed)).toEqual({ properties: stored.properties })
    })

    test.each([
        ['an "any" group', draft([PRODUCTION, PRODUCTION], {}, FilterLogicalOperator.Or), 'Switch "Any" to "All"'],
        [
            'a nested group',
            draft([{ type: FilterLogicalOperator.And, values: [PRODUCTION] }]),
            'do not support nested groups',
        ],
        [
            'a person property',
            draft([{ key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.Exact, value: ['a'] }]),
            'Remove the others',
        ],
        [
            'an issue assignee leaf',
            draft([{ key: 'assignee', type: PropertyFilterType.ErrorTrackingIssue, operator: PropertyOperator.Exact }]),
            'Use the assignee control',
        ],
        [
            'a leaf without a value',
            draft([{ key: '$environment', type: PropertyFilterType.Event, operator: PropertyOperator.IsNot }]),
            'Pick a value for $environment',
        ],
    ])('refuses to save %s', (_name, input, message) => {
        const payload = issueFilterPayloadFromDraft(input)
        expect('error' in payload && payload.error).toContain(message)
    })

    it('saves the assignee in the compact form lifecycle events carry', () => {
        const payload = issueFilterPayloadFromDraft(draft([], { assignee: { type: 'role', id: 'role-uuid' } }))
        expect(payload).toEqual({
            properties: [
                { key: 'assignee', type: 'event', operator: 'exact', value: ['{"type":"role","id":"role-uuid"}'] },
            ],
        })
    })

    it('replaces an earlier quick filter pick on the same property', () => {
        const once = withQuickFilterPick(draft([]).filterGroup, '$environment', {
            operator: PropertyOperator.Exact,
            value: ['staging'],
        })
        const twice = withQuickFilterPick(once, '$environment', {
            operator: PropertyOperator.Exact,
            value: ['production'],
        })

        expect((twice.values[0] as UniversalFiltersGroup).values).toEqual([PRODUCTION])
        expect((withQuickFilterPick(twice, '$environment', null).values[0] as UniversalFiltersGroup).values).toEqual([])
    })
})
