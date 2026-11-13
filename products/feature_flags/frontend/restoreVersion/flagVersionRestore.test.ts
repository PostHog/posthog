import type { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { flagVersionOfActivity, restoreVersionDisabledReason } from './flagVersionRestore'

const entry = (overrides: Partial<ActivityLogItem>): ActivityLogItem => ({
    activity: 'updated',
    created_at: '2026-01-01T00:00:00Z',
    scope: 'FeatureFlag',
    item_id: '1',
    detail: { changes: [], merge: null, trigger: null, name: null },
    ...overrides,
})

const restorableFlag = {
    version: 4,
    deleted: false,
    archived: false,
    has_encrypted_payloads: false,
    can_edit: true,
    filters: { groups: [] },
}

describe('flagVersionRestore', () => {
    test.each([
        ['a creation is version 1', entry({ activity: 'created' }), 1],
        [
            'an update is the version it moved to',
            entry({
                detail: {
                    merge: null,
                    trigger: null,
                    name: null,
                    changes: [
                        {
                            type: ActivityScope.FEATURE_FLAG,
                            action: 'changed',
                            field: 'filters',
                            before: {},
                            after: {},
                        },
                        { type: ActivityScope.FEATURE_FLAG, action: 'changed', field: 'version', before: 2, after: 3 },
                    ],
                },
            }),
            3,
        ],
        ['an update without a version change has none', entry({}), null],
        ['another scope has none', entry({ scope: 'Cohort', activity: 'created' }), null],
    ])('%s', (_name, logItem, expected) => {
        expect(flagVersionOfActivity(logItem)).toEqual(expected)
    })

    test.each([
        ['a past version of an editable flag', {}, 2, null],
        ['the current version', {}, 4, 'This is the current version.'],
        ['without edit access', { can_edit: false }, 2, "You don't have permission to edit this flag."],
        ['a deleted flag', { deleted: true }, 2, 'Restore this flag to restore a past version.'],
        ['an archived flag', { archived: true }, 2, 'Unarchive this flag to restore a past version.'],
        [
            'encrypted payloads',
            { has_encrypted_payloads: true },
            2,
            "Past versions of a flag with encrypted payloads can't be restored.",
        ],
        ['config version 2', { filters: { version: 2 } }, 2, "Past versions of this flag can't be restored yet."],
    ])('restore of %s', (_name, overrides, version, expected) => {
        expect(restoreVersionDisabledReason({ ...restorableFlag, ...overrides } as any, version)).toEqual(expected)
    })
})
