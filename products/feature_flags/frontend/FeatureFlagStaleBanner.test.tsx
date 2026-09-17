import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { NEW_FLAG, featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagsTab } from 'scenes/feature-flags/featureFlagsLogic'

import { useMocks } from '~/mocks/jest'
import type { Mocks } from '~/mocks/utils'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType } from '~/types'

import { FeatureFlagStaleBanner } from './FeatureFlagStaleBanner'

jest.mock('posthog-js')

const FLAG_ID = 1
const ACTION_SELECTOR = '[data-attr="feature-flag-stale-banner-view-usage"]'

const HEADING = 'This flag may no longer be needed'
const GUIDANCE = 'Review usage and code references before disabling or archiving this flag.'
const STALE_REASON = 'This boolean flag will always evaluate to "true"'

// One condition covering everyone with no property filters, which is what the summary reports for
// a flag whose only condition omits its rollout percentage.
const FULL_ROLLOUT = {
    effectively_full_rollout: false,
    has_targeting_conditions: false,
    max_rollout_percentage: 100,
    is_multivariate: false,
}

// The backend reached the stale verdict from evaluation data, so `reason` says nothing about the
// rollout and the banner is free to describe it.
const STALE_STATUS = {
    status: 'stale',
    reason: STALE_REASON,
    reason_states_rollout: false,
    rollout: FULL_ROLLOUT,
}

const ACTIVE_STATUS = {
    status: 'active',
    reason: 'Flag was called today',
    reason_states_rollout: false,
    rollout: FULL_ROLLOUT,
}

function buildFlag(overrides: Partial<FeatureFlagType> = {}): FeatureFlagType {
    return { ...NEW_FLAG, id: FLAG_ID, key: 'test-flag', name: 'test-name', ...overrides }
}

describe('FeatureFlagStaleBanner', () => {
    function endpointMocks({
        flag = buildFlag(),
        status = STALE_STATUS as unknown,
        statusCode = 200,
        dependentFlags = [] as { id: number; key: string; name: string }[],
    } = {}): Mocks {
        return {
            get: {
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/`]: () => [200, flag],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/status`]: () => [
                    statusCode,
                    status,
                ],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/dependent_flags/`]: () => [
                    200,
                    dependentFlags,
                ],
            },
        }
    }

    function mountAndRender(id: number | 'new' = FLAG_ID): ReturnType<typeof featureFlagLogic.build> {
        const logicProps = { id }
        const logic = featureFlagLogic(logicProps)
        logic.mount()
        render(
            <Provider>
                <BindLogic logic={featureFlagLogic} props={logicProps}>
                    <FeatureFlagStaleBanner />
                </BindLogic>
            </Provider>
        )
        return logic
    }

    async function settle(logic: ReturnType<typeof featureFlagLogic.build>): Promise<void> {
        await act(async () => {
            await expectLogic(logic).toFinishAllListeners()
        })
    }

    beforeEach(() => {
        initKeaTests()
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    it('explains a stale flag and offers a way to check its usage', async () => {
        // The reason already states the rollout, so no rollout line joins it and the reason can be
        // matched exactly. The rollout lines have their own cases below.
        useMocks(endpointMocks({ status: { ...STALE_STATUS, reason_states_rollout: true } }))
        const logic = mountAndRender()
        await settle(logic)

        expect(screen.getByText(HEADING)).toBeInTheDocument()
        expect(screen.getByText(`${STALE_REASON}.`)).toBeInTheDocument()
        expect(screen.getByText(GUIDANCE)).toBeInTheDocument()
        expect(document.querySelectorAll(ACTION_SELECTOR).length).toBeGreaterThan(0)
    })

    // Reading `stale` as "proven safe to delete" is the failure this banner exists to prevent, so a
    // rollout must never read as a larger or smaller share of users than it is.
    it.each([
        {
            name: 'a flag that covers everyone',
            flag: buildFlag(),
            rollout: { ...FULL_ROLLOUT, effectively_full_rollout: true },
            says: /One release condition rolls out to all users\./,
        },
        {
            // One 100% condition plus one 100% variant satisfies the full-rollout check while a
            // targeted condition above it serves a different variant, so both flags come back true
            // and the full-rollout sentence would be false.
            name: 'a multivariate flag that targets a subset and also covers everyone',
            flag: buildFlag(),
            rollout: {
                effectively_full_rollout: true,
                has_targeting_conditions: true,
                max_rollout_percentage: 40,
                is_multivariate: true,
            },
            says: /Its highest rollout across release conditions is 40%\. Some conditions target specific users, so this may not be 40% of all users\./,
        },
        {
            // The shape `max_rollout_percentage_across_multiple_groups` pins in
            // products/feature_flags/backend/test/test_flag_status.py: a 30% targeted condition next
            // to a 75% blanket one. The maximum belongs to the blanket condition, so the banner must
            // not place it inside the targeted one.
            name: 'a flag whose largest rollout sits outside its targeted condition',
            flag: buildFlag(),
            rollout: { ...FULL_ROLLOUT, has_targeting_conditions: true, max_rollout_percentage: 75 },
            says: /Its highest rollout across release conditions is 75%\. Some conditions target specific users, so this may not be 75% of all users\./,
        },
        {
            // Stale from the rollout alone, so the reason already carries the coverage. Appending a
            // percentage here reads as a contradiction next to 'will always evaluate to "true"'.
            name: 'a targeted flag the backend calls stale from its rollout alone',
            flag: buildFlag(),
            reasonStatesRollout: true,
            rollout: { ...FULL_ROLLOUT, effectively_full_rollout: true, has_targeting_conditions: true },
            says: null,
        },
        {
            name: 'a flag that still serves part of the user base',
            flag: buildFlag(),
            rollout: { ...FULL_ROLLOUT, max_rollout_percentage: 40 },
            says: /Its rollout is 40% of all users\./,
        },
        {
            // A rollout written through the API keeps more precision than the editor allows, and the
            // raw float reads as a bug. FractionalRolloutWarning on the same page trims it the same way.
            name: 'a flag on a high-precision fractional rollout',
            flag: buildFlag(),
            rollout: { ...FULL_ROLLOUT, max_rollout_percentage: 33.333333333333336 },
            says: /Its rollout is 33.33% of all users\./,
        },
        {
            // A boolean flag whose only condition omits its percentage evaluates to 100% at runtime,
            // so max_rollout_percentage is 100 while effectively_full_rollout stays false. It still
            // reaches everyone, and the banner must say so rather than fall silent.
            name: 'a boolean flag whose condition omits its rollout percentage',
            flag: buildFlag(),
            rollout: { ...FULL_ROLLOUT },
            says: /One release condition rolls out to all users\./,
        },
        {
            // is_multivariate reports only that variants exist, not how traffic divides. A single
            // 100% variant produces the same summary as a real split, so the banner cannot claim a
            // split; it states the coverage both shapes share.
            name: 'a multivariate flag that covers everyone',
            flag: buildFlag(),
            rollout: { ...FULL_ROLLOUT, is_multivariate: true },
            says: /One release condition rolls out to all users\./,
        },
        {
            // `effectively_full_rollout` is true for a flag with no release conditions, so a
            // sentence about a condition would describe something that is not there.
            name: 'a flag with no release conditions',
            flag: buildFlag(),
            rollout: { ...FULL_ROLLOUT, effectively_full_rollout: true, max_rollout_percentage: null },
            says: null,
        },
        {
            // The backend read the rollout to reach its verdict, so the reason already carries the
            // fact and the banner must not repeat it.
            name: 'a flag the backend calls stale from its rollout alone',
            flag: buildFlag(),
            reasonStatesRollout: true,
            rollout: { ...FULL_ROLLOUT, effectively_full_rollout: true },
            says: null,
        },
    ])('describes the rollout of $name', async ({ flag, rollout, says, reasonStatesRollout }) => {
        useMocks(
            endpointMocks({
                flag,
                status: { ...STALE_STATUS, rollout, reason_states_rollout: Boolean(reasonStatesRollout) },
            })
        )
        const logic = mountAndRender()
        await settle(logic)

        // The reason and the rollout share one paragraph, so an exact match on the reason alone
        // proves that no rollout sentence was added to it.
        expect(screen.getByText(says ?? `${STALE_REASON}.`)).toBeInTheDocument()
    })

    it('names the aggregation unit for a group-based flag', async () => {
        // A flag evaluated on organizations serves a share of organizations, not users, and the rest
        // of the flag page already says so. Seed the group type so the label resolves to a real noun.
        groupsModel.mount()
        groupsModel.actions.loadAllGroupTypesSuccess([
            {
                group_type: 'organization',
                group_type_index: 0,
                name_singular: 'organization',
                name_plural: 'organizations',
            },
        ] as any)

        const flag = buildFlag({ filters: { ...NEW_FLAG.filters, aggregation_group_type_index: 0 } })
        useMocks(
            endpointMocks({
                flag,
                status: { ...STALE_STATUS, rollout: { ...FULL_ROLLOUT, max_rollout_percentage: 40 } },
            })
        )
        const logic = mountAndRender()
        await settle(logic)

        expect(screen.getByText(/Its rollout is 40% of all organizations\./)).toBeInTheDocument()
    })

    it.each([
        { name: 'the flag is not stale', flag: buildFlag(), status: ACTIVE_STATUS, statusCode: 200 },
        { name: 'the flag is deleted', flag: buildFlag({ deleted: true }), status: STALE_STATUS, statusCode: 200 },
        { name: 'the flag is archived', flag: buildFlag({ archived: true }), status: STALE_STATUS, statusCode: 200 },
        {
            name: 'the flag is remote configuration',
            flag: buildFlag({ is_remote_configuration: true }),
            status: STALE_STATUS,
            statusCode: 200,
        },
        { name: 'the status request failed', flag: buildFlag(), status: {}, statusCode: 500 },
    ])('renders nothing when $name', async ({ flag, status, statusCode }) => {
        useMocks(endpointMocks({ flag, status, statusCode }))
        const logic = mountAndRender()
        await settle(logic)

        expect(screen.queryByText(HEADING)).not.toBeInTheDocument()
    })

    it('renders nothing for an unsaved flag', async () => {
        useMocks(endpointMocks())
        const logic = mountAndRender('new')
        await settle(logic)

        expect(screen.queryByText(HEADING)).not.toBeInTheDocument()
    })

    it('does not flash while the status request is in flight', async () => {
        useMocks(endpointMocks())
        const logic = mountAndRender()

        expect(screen.queryByText(HEADING)).not.toBeInTheDocument()

        await settle(logic)
        expect(screen.getByText(HEADING)).toBeInTheDocument()
    })

    it('warns that an experiment is linked to the flag', async () => {
        useMocks(endpointMocks({ flag: buildFlag({ experiment_set: [123] }) }))
        const logic = mountAndRender()
        await settle(logic)

        expect(screen.getByText('This flag is linked to an experiment.')).toBeInTheDocument()
    })

    it('warns that other flags depend on the flag', async () => {
        useMocks(endpointMocks({ dependentFlags: [{ id: 2, key: 'dependent-flag', name: 'Dependent flag' }] }))
        const logic = mountAndRender()
        logic.actions.loadDependentFlags()
        await settle(logic)

        expect(screen.getByText('Other flags depend on this flag.')).toBeInTheDocument()
    })

    it('opens the usage tab and reports the click', async () => {
        useMocks(endpointMocks())
        const logic = mountAndRender()
        await settle(logic)

        act(() => {
            document.querySelector<HTMLElement>(ACTION_SELECTOR)?.click()
        })

        expect(logic.values.activeTab).toBe(FeatureFlagsTab.USAGE)
        expect(posthog.capture).toHaveBeenCalledWith('feature flag stale banner view usage clicked')
    })
})
