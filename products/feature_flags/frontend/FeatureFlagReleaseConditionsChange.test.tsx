import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagFilters, PropertyFilterType, PropertyOperator } from '~/types'

import { FeatureFlagReleaseConditionsChange } from './FeatureFlagReleaseConditionsChange'

const before: FeatureFlagFilters = {
    groups: [
        {
            properties: [
                {
                    type: PropertyFilterType.Person,
                    key: 'distinct_id',
                    operator: PropertyOperator.Exact,
                    value: ['user-7'],
                },
                {
                    type: PropertyFilterType.Flag,
                    key: '42',
                    operator: PropertyOperator.FlagEvaluatesTo,
                    value: true,
                },
            ],
            rollout_percentage: 100,
        },
    ],
    multivariate: null,
}

const after: FeatureFlagFilters = {
    groups: [{ properties: [], rollout_percentage: 100 }],
    multivariate: null,
}

describe('FeatureFlagReleaseConditionsChange', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            post: {
                '/api/projects/:team/feature_flags/bulk_keys/': [200, { keys: { '42': 'beta-banner' } }],
                '/api/environments/:team/persons/batch_by_distinct_ids/': [
                    200,
                    { results: { 'user-7': { name: 'Ada Lovelace' } } },
                ],
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('resolves distinct id and flag names in a removed condition set', async () => {
        render(
            <Provider>
                <FeatureFlagReleaseConditionsChange flagId="1234" activityId="removal" before={before} after={after} />
            </Provider>
        )

        await screen.findByText('user-7 (Ada Lovelace)')
        const removedCard = screen.getByText('Was set 1').closest('div.border') as HTMLElement
        expect(within(removedCard).getByText('user-7 (Ada Lovelace)')).toBeInTheDocument()
        expect(within(removedCard).getByText('beta-banner')).toBeInTheDocument()
    })
})
