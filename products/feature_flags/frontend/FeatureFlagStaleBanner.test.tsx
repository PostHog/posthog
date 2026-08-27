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
import { initKeaTests } from '~/test/init'
import { FeatureFlagType } from '~/types'

import { FeatureFlagStaleBanner } from './FeatureFlagStaleBanner'

jest.mock('posthog-js')

const FLAG_ID = 1
const ACTION_SELECTOR = '[data-attr="feature-flag-stale-banner-view-usage"]'

const HEADING = 'This flag may no longer be needed'
const GUIDANCE = 'Review usage and code references before disabling or archiving this flag.'
const STALE_REASON = 'This boolean flag will always evaluate to "true"'

const NO_ROLLOUT = {
    effectively_full_rollout: false,
    has_targeting_conditions: false,
    max_rollout_percentage: 100,
    is_multivariate: false,
}

const STALE_STATUS = {
    status: 'stale',
    reason: STALE_REASON,
    rollout: NO_ROLLOUT,
}

const ACTIVE_STATUS = {
    status: 'active',
    reason: 'Flag was called today',
    rollout: NO_ROLLOUT,
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
        useMocks(endpointMocks())
        const logic = mountAndRender()
        await settle(logic)

        expect(screen.getByText(HEADING)).toBeInTheDocument()
        expect(screen.getByText(`${STALE_REASON}.`)).toBeInTheDocument()
        expect(screen.getByText(GUIDANCE)).toBeInTheDocument()
        expect(document.querySelectorAll(ACTION_SELECTOR).length).toBeGreaterThan(0)
    })

    // Reading `stale` as "proven safe to delete" is the failure this banner exists to prevent,
    // so a partial rollout must never be reported as a share of every user.
    it.each([
        {
            name: 'a flag that resolves the same way for everyone',
            rollout: { ...NO_ROLLOUT, effectively_full_rollout: true },
            expected: /resolves to one result for all users/,
        },
        {
            name: 'a flag whose biggest rollout sits inside a targeted condition',
            rollout: { ...NO_ROLLOUT, has_targeting_conditions: true, max_rollout_percentage: 40 },
            expected: /highest rollout is 40% within a targeted condition, not 40% of all users/,
        },
    ])('describes the rollout of $name', async ({ rollout, expected }) => {
        useMocks(endpointMocks({ status: { ...STALE_STATUS, rollout } }))
        const logic = mountAndRender()
        await settle(logic)

        expect(screen.getByText(expected)).toBeInTheDocument()
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
