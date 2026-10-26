import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

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

function buildFlag(
    overrides: Partial<FeatureFlagType> = {},
    cohortOverrides: Record<string, unknown> = {}
): FeatureFlagType {
    return {
        ...NEW_FLAG,
        id: FLAG_ID,
        key: 'test-flag',
        can_edit: true,
        filters: {
            groups: [
                {
                    properties: [cohortProperty(5, { cohort_deleted: true, ...cohortOverrides })],
                    rollout_percentage: 100,
                },
            ],
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

    async function renderBanner(): Promise<ReturnType<typeof featureFlagLogic.build>> {
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
        return logic
    }

    beforeEach(() => {
        initKeaTests()
        jest.mocked(posthog.capture).mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            state: 'an active flag',
            flag: buildFlag({ active: true }),
            says: /^Cohort 'Frequent buyers' was deleted\. The flag fails to evaluate for anyone who reaches a release condition that targets it\. Restore the cohort or update the release conditions to remove it\.$/,
            showsEdit: true,
        },
        {
            state: 'a disabled flag',
            flag: buildFlag({ active: false }),
            says: /You can't enable the flag until you restore the cohort or update the release conditions to remove it\.$/,
            showsEdit: true,
        },
        {
            state: 'an archived flag',
            flag: buildFlag({ active: false, archived: true }),
            says: /You can't unarchive the flag until you restore the cohort or update the release conditions to remove it\.$/,
            showsEdit: true,
        },
        {
            state: 'a deleted flag',
            flag: buildFlag({ active: true, deleted: true }),
            says: /You can't restore the flag until you restore the cohort or update the release conditions to remove it\.$/,
            showsEdit: true,
        },
        {
            // Restoring leaves the flag archived, so the flag API skips the cohort check until the flag is unarchived.
            state: 'a deleted and archived flag',
            flag: buildFlag({ active: false, deleted: true, archived: true }),
            says: /You can't unarchive the flag until you restore the cohort or update the release conditions to remove it\.$/,
            showsEdit: true,
        },
        {
            state: 'a flag the user cannot edit',
            flag: buildFlag({ active: true, can_edit: false }),
            says: /Restore the cohort or update the release conditions to remove it\.$/,
            showsEdit: false,
        },
        {
            state: 'a flag whose deleted cohort has no name',
            flag: buildFlag({ active: true }, { cohort_name: undefined }),
            says: /^Cohort ID 5 was deleted\. .* Restore the cohort or update the release conditions to remove it\.$/,
            showsEdit: true,
        },
        {
            state: 'a flag whose cohort no longer exists',
            flag: buildFlag({ active: true }, { cohort_name: undefined, cohort_missing: true }),
            says: /^Cohort ID 5 does not exist in this project\. The flag fails to evaluate for anyone who reaches a release condition that targets it\. Update the release conditions to remove it\.$/,
            showsEdit: true,
        },
        {
            state: 'a deleted flag whose cohort no longer exists',
            flag: buildFlag({ active: true, deleted: true }, { cohort_name: undefined, cohort_missing: true }),
            says: /You can't restore the flag until you update the release conditions to remove it\.$/,
            showsEdit: true,
        },
        {
            state: 'a flag with two deleted cohorts where one no longer exists',
            flag: buildFlag({
                active: true,
                filters: {
                    groups: [
                        {
                            properties: [
                                cohortProperty(5, { cohort_deleted: true }),
                                cohortProperty(6, {
                                    cohort_deleted: true,
                                    cohort_name: undefined,
                                    cohort_missing: true,
                                }),
                            ],
                            rollout_percentage: 100,
                        },
                    ],
                },
            }),
            says: /^Cohort 'Frequent buyers' was deleted\. Cohort ID 6 does not exist in this project\. .* Update the release conditions to remove them\.$/,
            showsEdit: true,
        },
    ])('gives the next step for $state', async ({ flag, says, showsEdit }) => {
        useMocks(endpointMocks(flag))
        await renderBanner()

        expect(screen.getByText(/^Cohorts? /)).toHaveTextContent(says)
        expect(document.querySelectorAll(EDIT_SELECTOR).length > 0).toBe(showsEdit)
    })

    it('reports a flag with a deleted cohort once when the user starts editing it', async () => {
        useMocks(endpointMocks(buildFlag({ active: true })))
        const logic = await renderBanner()

        await act(async () => {
            fireEvent.click(document.querySelector(EDIT_SELECTOR)!)
            await expectLogic(logic).toFinishAllListeners()
        })

        expect(logic.values.isEditingFlag).toBe(true)
        expect(posthog.capture).toHaveBeenCalledWith('feature flag deleted cohort banner edit clicked')
        const loadedCaptures = jest
            .mocked(posthog.capture)
            .mock.calls.filter(([event]) => event === 'feature flag with deleted cohort loaded')
        expect(loadedCaptures).toHaveLength(1)
    })

    const deletedCohort = (value: number | string): AnyPropertyFilter => cohortProperty(value, { cohort_deleted: true })
    const missingCohort = (value: number): AnyPropertyFilter =>
        cohortProperty(value, { cohort_deleted: true, cohort_missing: true, cohort_name: undefined })

    it.each([
        {
            name: 'one cohort stored as a number and as a string',
            properties: [deletedCohort(5), deletedCohort('5')],
            heading: 'This flag targets a deleted cohort',
        },
        {
            name: 'two deleted cohorts',
            properties: [deletedCohort(5), deletedCohort(6)],
            heading: 'This flag targets deleted cohorts',
        },
        { name: 'a missing cohort', properties: [missingCohort(5)], heading: 'This flag targets a missing cohort' },
        {
            name: 'a deleted and a missing cohort',
            properties: [deletedCohort(5), missingCohort(6)],
            heading: 'This flag targets deleted and missing cohorts',
        },
    ])('gives the heading for $name', async ({ properties, heading }) => {
        useMocks(
            endpointMocks(
                buildFlag({
                    filters: {
                        groups: properties.map((property) => ({ properties: [property], rollout_percentage: 100 })),
                    },
                })
            )
        )
        await renderBanner()

        expect(screen.getByText(heading)).toBeInTheDocument()
    })

    it.each([
        {
            name: 'no condition targets a deleted cohort',
            filters: { groups: [{ properties: [cohortProperty(5)], rollout_percentage: 100 }] },
        },
        {
            name: 'the flag is in an unsupported config version',
            filters: {
                version: 3,
                groups: [{ properties: [cohortProperty(5, { cohort_deleted: true })], rollout_percentage: 100 }],
            } as unknown as FeatureFlagType['filters'],
        },
    ])('renders nothing when $name', async ({ filters }) => {
        useMocks(endpointMocks(buildFlag({ filters })))
        await renderBanner()

        expect(screen.queryByText(/deleted cohort/)).not.toBeInTheDocument()
    })
})
