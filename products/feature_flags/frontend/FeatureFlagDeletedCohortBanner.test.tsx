import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { NEW_FLAG, featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import type { Mocks } from '~/mocks/utils'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import { FeatureFlagDeletedCohortBanner } from './FeatureFlagDeletedCohortBanner'

jest.mock('posthog-js')

const FLAG_ID = 1
const EDIT_SELECTOR = '[data-attr="feature-flag-deleted-cohort-banner-edit"]'

function cohortProperty(value: number | string, overrides: Record<string, unknown> = {}): AnyPropertyFilter {
    return {
        key: 'id',
        type: PropertyFilterType.Cohort,
        operator: PropertyOperator.In,
        value,
        cohort_name: 'Frequent buyers',
        ...overrides,
    } as AnyPropertyFilter
}

function buildFlag(overrides: Partial<FeatureFlagType> = {}): FeatureFlagType {
    return {
        ...NEW_FLAG,
        id: FLAG_ID,
        key: 'test-flag',
        can_edit: true,
        filters: {
            groups: [{ properties: [cohortProperty(5, { cohort_deleted: true })], rollout_percentage: 100 }],
        },
        ...overrides,
    }
}

describe('FeatureFlagDeletedCohortBanner', () => {
    function endpointMocks(flag: FeatureFlagType): Mocks {
        return {
            get: {
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${FLAG_ID}/`]: () => [200, flag],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${FLAG_ID}/status`]: () => [
                    200,
                    { status: 'active', reason: '', reason_states_rollout: false },
                ],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${FLAG_ID}/dependent_flags/`]: () => [200, []],
            },
        }
    }

    async function renderBanner(): Promise<void> {
        const logicProps = { id: FLAG_ID }
        const logic = featureFlagLogic(logicProps)
        logic.mount()
        render(
            <Provider>
                <BindLogic logic={featureFlagLogic} props={logicProps}>
                    <FeatureFlagDeletedCohortBanner />
                </BindLogic>
            </Provider>
        )
        await act(async () => {
            await expectLogic(logic).toFinishAllListeners()
        })
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            state: 'an active flag',
            flag: buildFlag({ active: true }),
            says: /The flag fails to evaluate for anyone who reaches a release condition that targets it\. Restore the cohort or update the release conditions to remove it\./,
            canEdit: true,
        },
        {
            state: 'a disabled flag',
            flag: buildFlag({ active: false }),
            says: /You can't enable the flag until you restore the cohort or update the release conditions to remove it\./,
            canEdit: true,
        },
        {
            state: 'an archived flag',
            flag: buildFlag({ active: false, archived: true }),
            says: /You can't unarchive the flag until you restore the cohort or update the release conditions to remove it\./,
            canEdit: true,
        },
        {
            state: 'a deleted flag',
            flag: buildFlag({ active: true, deleted: true }),
            says: /You can't restore the flag while it targets it\. Restore the cohort first\./,
            canEdit: false,
        },
    ])('gives the next step for $state', async ({ flag, says, canEdit }) => {
        useMocks(endpointMocks(flag))
        await renderBanner()

        expect(screen.getByText(/Cohort 'Frequent buyers' was deleted\./)).toHaveTextContent(says)
        expect(document.querySelectorAll(EDIT_SELECTOR).length > 0).toBe(canEdit)
    })

    it('names a cohort once when conditions store its id as a number and as a string', async () => {
        useMocks(
            endpointMocks(
                buildFlag({
                    filters: {
                        groups: [
                            { properties: [cohortProperty(5, { cohort_deleted: true })], rollout_percentage: 100 },
                            { properties: [cohortProperty('5', { cohort_deleted: true })], rollout_percentage: 50 },
                        ],
                    },
                })
            )
        )
        await renderBanner()

        expect(screen.getByText('This flag targets a deleted cohort')).toBeInTheDocument()
    })

    it.each([
        {
            name: 'no condition targets a deleted cohort',
            filters: { groups: [{ properties: [cohortProperty(5)], rollout_percentage: 100 }] },
        },
        {
            name: 'the flag uses rules v2',
            filters: { version: 2, rules: [] } as unknown as FeatureFlagType['filters'],
        },
    ])('renders nothing when $name', async ({ filters }) => {
        useMocks(endpointMocks(buildFlag({ filters })))
        await renderBanner()

        expect(screen.queryByText(/deleted cohort/)).not.toBeInTheDocument()
    })
})
