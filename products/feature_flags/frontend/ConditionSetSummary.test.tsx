import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { FeatureFlagGroupType, PropertyFilterType, PropertyOperator } from '~/types'

import { ConditionSetSummary } from './ConditionSetSummary'

function group(rolloutPercentage: number | null, withProperties = false): FeatureFlagGroupType {
    return {
        properties: withProperties
            ? [
                  {
                      type: PropertyFilterType.Person,
                      key: 'email',
                      operator: PropertyOperator.IContains,
                      value: 'example.com',
                  },
              ]
            : [],
        rollout_percentage: rolloutPercentage,
        variant: null,
        sort_key: 'group-1',
    }
}

describe('ConditionSetSummary', () => {
    afterEach(() => {
        cleanup()
    })

    it.each<[number | null, string]>([
        [100, 'Condition set will match all users'],
        [null, 'Condition set will match all users'],
        [25, 'Condition set will match 25% of all users'],
        [0, 'Condition set will match no users'],
    ])('summarises a set without criteria at %s%% rollout', (rolloutPercentage, expected) => {
        render(<ConditionSetSummary group={group(rolloutPercentage)} aggregationTargetName="users" />)

        expect(document.body).toHaveTextContent(expected)
    })

    it('summarises a set with criteria', () => {
        render(<ConditionSetSummary group={group(25, true)} aggregationTargetName="users" />)

        expect(document.body).toHaveTextContent('Match users against all criteria')
    })
})
