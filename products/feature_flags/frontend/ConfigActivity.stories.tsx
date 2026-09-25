import type { Meta } from '@storybook/react'

import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLogRow'
import { ActivityLogItem, humanize } from 'lib/components/ActivityLog/humanizeActivity'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'

import { ActivityScope } from '~/types'

const ruleId = '00000000-0000-4000-8000-000000000001'
const otherRuleId = '00000000-0000-4000-8000-000000000003'
const item: ActivityLogItem = {
    id: '00000000-0000-4000-8000-000000000002',
    scope: ActivityScope.FEATURE_FLAG,
    activity: 'updated',
    item_id: '42',
    created_at: '2026-01-01T10:00:00Z',
    user: { first_name: 'Robin', last_name: 'Lee', email: 'robin@example.com' },
    detail: {
        name: 'example-release',
        merge: null,
        trigger: null,
        changes: [
            {
                type: ActivityScope.FEATURE_FLAG,
                field: 'filters',
                action: 'changed',
                before: 'masked',
                after: 'masked',
            },
        ],
        context: {
            filters_version: 2,
            config_changes: [
                { field: 'default_value', action: 'changed' },
                { field: `rules/${ruleId}/metadata`, action: 'created' },
                { field: `rules/${ruleId}/description`, action: 'deleted' },
                {
                    field: 'rule_order',
                    action: 'changed',
                    before: [ruleId, otherRuleId],
                    after: [otherRuleId, ruleId],
                },
            ],
        },
    },
}

const meta: Meta<typeof ActivityLogRow> = {
    title: 'Scenes-App/Feature Flags/Config Activity',
    component: ActivityLogRow,
    parameters: { mockDate: '2026-01-01T12:00:00Z' },
}
export default meta

export function Version2(): JSX.Element {
    return <ActivityLogRow logItem={humanize([item], () => flagActivityDescriber)[0]} />
}
