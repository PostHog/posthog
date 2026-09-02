import { Meta } from '@storybook/react'

import { FeatureFlagFilters, FeatureFlagGroupType, PropertyFilterType, PropertyOperator } from '~/types'

import { FeatureFlagReleaseConditionsChange } from './FeatureFlagReleaseConditionsChange'

const meta: Meta<typeof FeatureFlagReleaseConditionsChange> = {
    title: 'Scenes-App/Feature Flags/Release Conditions Change',
    component: FeatureFlagReleaseConditionsChange,
}
export default meta

const ORG_A = '00000000-0000-0000-0000-00000000000a'
const ORG_B = '00000000-0000-0000-0000-00000000000b'

function organizationSet(
    orgIds: string[],
    rollout: number,
    operator: PropertyOperator = PropertyOperator.Exact,
    description?: string
): FeatureFlagGroupType {
    return {
        properties: [
            { key: 'organization_id', type: PropertyFilterType.Group, group_type_index: 0, operator, value: orgIds },
        ],
        rollout_percentage: rollout,
        description,
        aggregation_group_type_index: 0,
    }
}

function everyone(rollout: number): FeatureFlagGroupType {
    return { properties: [], rollout_percentage: rollout }
}

function filters(groups: FeatureFlagGroupType[]): FeatureFlagFilters {
    return { groups, multivariate: null }
}

export function RolloutChanged(): JSX.Element {
    return (
        <div className="max-w-3xl">
            <FeatureFlagReleaseConditionsChange
                flagId="1234"
                activityId="rollout"
                before={filters([everyone(75)])}
                after={filters([everyone(100)])}
            />
        </div>
    )
}

export function SetsAddedChangedAndRemoved(): JSX.Element {
    return (
        <div className="max-w-3xl">
            <FeatureFlagReleaseConditionsChange
                flagId="1234"
                activityId="restructure"
                before={filters([
                    organizationSet([ORG_A], 0, PropertyOperator.Exact, 'Disabled for org A'),
                    organizationSet([ORG_B], 100),
                    everyone(100),
                ])}
                after={filters([
                    organizationSet([ORG_A], 0, PropertyOperator.Exact, 'Disabled for org A'),
                    organizationSet([ORG_B], 50),
                    organizationSet([ORG_A, ORG_B], 100, PropertyOperator.IsNot),
                ])}
            />
        </div>
    )
}
