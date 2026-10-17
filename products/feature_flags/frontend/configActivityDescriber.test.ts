import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { describeConfigActivity } from './configActivityDescriber'

describe('config activity descriptions', () => {
    const change: ActivityChange = {
        type: ActivityScope.FEATURE_FLAG,
        action: 'changed',
        field: 'filters',
        before: { version: 2, rules: [{ seed: 'private-seed' }] },
        after: { version: 2, rules: [{ metadata: { secret: 'opaque-value' } }] },
    }
    const item: ActivityLogItem = {
        scope: ActivityScope.FEATURE_FLAG,
        activity: 'updated',
        created_at: '2026-01-01T00:00:00Z',
        detail: { name: 'example', changes: [change], trigger: null, merge: null },
    }

    it('describes stable identities and order without rendering config values', () => {
        const result = describeConfigActivity(change, {
            ...item,
            detail: {
                ...item.detail,
                context: {
                    filters_version: 2,
                    config_changes: [
                        { field: 'default_value', action: 'changed' },
                        { field: 'rules/rule-a', action: 'created' },
                        { field: 'rules/rule-b', action: 'deleted' },
                        { field: 'rules/rule-c/targeting', action: 'changed' },
                        { field: 'rules/rule-c/rollout_percentage', action: 'changed' },
                        { field: 'rules/rule-c/metadata', action: 'changed' },
                        { field: 'rule_order', action: 'changed' },
                    ],
                },
            },
        })
        expect(result?.description).toEqual([
            'changed the default value',
            'added rule rule-a',
            'removed rule rule-b',
            'changed targeting for rule rule-c',
            'changed rollout percentage for rule rule-c',
            'changed metadata for rule rule-c',
            'changed the rule order',
        ])
        expect(JSON.stringify(result)).not.toMatch(/private-seed|opaque-value/)
    })

    it.each([
        ['created', 'added'],
        ['deleted', 'removed'],
        ['changed', 'changed'],
    ])('describes %s configuration fields accurately', (action, verb) => {
        const result = describeConfigActivity(change, {
            ...item,
            detail: {
                ...item.detail,
                context: {
                    filters_version: 2,
                    config_changes: [
                        { field: 'aggregation_group_type_index', action },
                        { field: 'rules/rule-a/metadata', action },
                    ],
                },
            },
        })
        expect(result?.description).toEqual([`${verb} the aggregation group`, `${verb} metadata for rule rule-a`])
    })

    it.each([null, {}, { version: 1 }, { groups: [] }])(
        'leaves legacy config to the existing describer: %p',
        (value) => {
            expect(describeConfigActivity({ ...change, before: value, after: value }, item)).toBeNull()
        }
    )

    it.each([[], { version: null }, { version: true }, { version: '2' }, { version: 3 }, 'masked'])(
        'does not interpret unsupported config as legacy: %p',
        (value) => {
            expect(describeConfigActivity({ ...change, after: value }, item)?.description).toEqual([
                'changed the feature flag configuration',
            ])
        }
    )
})
