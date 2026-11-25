import { ActivityEntry, ChangeKind, describeChange } from './releaseChanges'

const AT = '2026-11-24T11:00:00Z'

function entry(changes: ActivityEntry['detail'], user: ActivityEntry['user'] = { first_name: 'Ana' }): ActivityEntry {
    return { id: 'entry-1', activity: 'updated', created_at: AT, user, detail: changes }
}

const everyone = { groups: [{ properties: [], rollout_percentage: 30 }] }

describe('releaseChanges', () => {
    test.each<{
        name: string
        kind: ChangeKind
        input: ActivityEntry
        who: string
        lines: string[]
        applied: string[]
    }>([
        {
            name: 'a cohort added to a condition set',
            kind: 'flag',
            input: entry({
                changes: [
                    {
                        field: 'filters',
                        before: { groups: [{ properties: [], rollout_percentage: 100 }] },
                        after: {
                            groups: [
                                {
                                    properties: [{ key: 'id', type: 'cohort', value: 7, cohort_name: 'Beta testers' }],
                                    rollout_percentage: 100,
                                },
                            ],
                        },
                    },
                ],
            }),
            who: 'Ana',
            lines: ['Added cohort Beta testers'],
            applied: ['cohort Beta testers · 100%'],
        },
        {
            name: 'an email condition at 30%',
            kind: 'flag',
            input: entry({
                changes: [
                    {
                        field: 'filters',
                        before: everyone,
                        after: {
                            groups: [
                                {
                                    properties: [
                                        { key: 'email', type: 'person', operator: 'icontains', value: 'example.com' },
                                    ],
                                    rollout_percentage: 30,
                                },
                            ],
                        },
                    },
                ],
            }),
            who: 'Ana',
            lines: ['Changed the conditions'],
            applied: ['email contains example.com · 30%'],
        },
        {
            name: 'a cohort excluded from a condition set',
            kind: 'flag',
            input: entry({
                changes: [
                    {
                        field: 'filters',
                        before: everyone,
                        after: {
                            groups: [
                                {
                                    properties: [
                                        {
                                            key: 'id',
                                            type: 'cohort',
                                            operator: 'not_in',
                                            value: 7,
                                            cohort_name: 'Beta testers',
                                        },
                                    ],
                                    rollout_percentage: 30,
                                },
                            ],
                        },
                    },
                ],
            }),
            who: 'Ana',
            lines: ['Added cohort Beta testers'],
            applied: ['not in cohort Beta testers · 30%'],
        },
        {
            name: 'a flag description edit',
            kind: 'flag',
            input: entry({ changes: [{ field: 'name', before: 'Old', after: 'New' }] }),
            who: 'Ana',
            lines: [],
            applied: [],
        },
        {
            name: 'a cohort added in a new condition set',
            kind: 'flag',
            input: entry({
                changes: [
                    {
                        field: 'filters',
                        before: { groups: [{ properties: [], rollout_percentage: 100 }] },
                        after: {
                            groups: [
                                { properties: [], rollout_percentage: 100 },
                                {
                                    properties: [{ key: 'id', type: 'cohort', value: 8, cohort_name: 'Postal codes' }],
                                    rollout_percentage: 100,
                                },
                            ],
                        },
                    },
                ],
            }),
            who: 'Ana',
            lines: ['Added cohort Postal codes'],
            applied: ['Everyone · 100%', 'cohort Postal codes · 100%'],
        },
        {
            name: 'a rollout from 30% to 100%',
            kind: 'flag',
            input: entry({
                changes: [
                    {
                        field: 'filters',
                        before: everyone,
                        after: { groups: [{ properties: [], rollout_percentage: 100 }] },
                    },
                    { field: 'version', before: 3, after: 4 },
                ],
            }),
            who: 'Ana',
            lines: ['Rollout 30% to 100%'],
            applied: ['Everyone · 100%'],
        },
        {
            name: 'a flag turned off by the system',
            kind: 'flag',
            input: entry({ changes: [{ field: 'active', before: true, after: false }] }, null),
            who: 'PostHog',
            lines: ['Turned off'],
            applied: [],
        },
        {
            name: 'an experiment launch',
            kind: 'experiment',
            input: entry({ changes: [{ field: 'start_date', before: null, after: AT }] }),
            who: 'Ana',
            lines: ['Launched'],
            applied: [],
        },
        {
            name: 'a shared metric deleted in an experiment history',
            kind: 'experiment',
            input: { ...entry({ type: 'shared_metric' }), activity: 'deleted', scope: 'Experiment' },
            who: 'Ana',
            lines: [],
            applied: [],
        },
        {
            name: 'a linked flag rollout in an experiment history',
            kind: 'experiment',
            input: {
                ...entry({
                    changes: [
                        {
                            field: 'filters',
                            before: everyone,
                            after: { groups: [{ properties: [], rollout_percentage: 100 }] },
                        },
                    ],
                }),
                scope: 'FeatureFlag',
            },
            who: 'Ana',
            lines: ['Rollout 30% to 100%'],
            applied: ['Everyone · 100%'],
        },
        {
            name: 'survey questions edited',
            kind: 'survey',
            input: entry({ changes: [{ field: 'questions', before: [], after: [{ question: 'Why?' }] }] }),
            who: 'Ana',
            lines: [],
            applied: [],
        },
    ])('describes $name', ({ kind, input, who, lines, applied }) => {
        expect(describeChange(kind, input)).toEqual(
            lines.length ? { key: 'entry-1', date: AT, who, lines, applied } : null
        )
    })
})
