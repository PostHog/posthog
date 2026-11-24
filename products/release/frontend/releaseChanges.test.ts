import { ActivityEntry, ChangeKind, describeChange } from './releaseChanges'

const AT = '2026-11-24T11:00:00Z'

function entry(changes: ActivityEntry['detail'], user: ActivityEntry['user'] = { first_name: 'Ana' }): ActivityEntry {
    return { id: 'entry-1', activity: 'updated', created_at: AT, user, detail: changes }
}

const everyone = { groups: [{ properties: [], rollout_percentage: 30 }] }

describe('releaseChanges', () => {
    test.each<{ name: string; kind: ChangeKind; input: ActivityEntry; who: string; lines: string[] }>([
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
        },
        {
            name: 'a flag turned off by the system',
            kind: 'flag',
            input: entry({ changes: [{ field: 'active', before: true, after: false }] }, null),
            who: 'PostHog',
            lines: ['Turned off'],
        },
        {
            name: 'an experiment launch',
            kind: 'experiment',
            input: entry({ changes: [{ field: 'start_date', before: null, after: AT }] }),
            who: 'Ana',
            lines: ['Launched'],
        },
        {
            name: 'survey questions edited',
            kind: 'survey',
            input: entry({ changes: [{ field: 'questions', before: [], after: [{ question: 'Why?' }] }] }),
            who: 'Ana',
            lines: ['Edited the questions'],
        },
    ])('describes $name', ({ kind, input, who, lines }) => {
        expect(describeChange(kind, input)).toEqual({ key: 'entry-1', date: AT, who, lines })
    })
})
